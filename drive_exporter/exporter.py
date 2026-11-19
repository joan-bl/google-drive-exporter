"""Ejecuta el plan: descarga, exporta, verifica y pone las fechas originales."""

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .names import long_path
from .state import State
from .timestamps import apply_times

STATUS_OK = "descargado"
STATUS_SAME = "sin cambios"
STATUS_MOVED = "movido"
STATUS_ERROR = "error"
STATUS_SKIP = "omitido"
STATUS_DUP = "duplicado"
STATUS_DRY = "simulado"
STATUS_FOLDER = "carpeta"


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(long_path(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Exporter:
    def __init__(self, client, out_dir: str, log=print, threads: int = 4):
        self.client = client
        self.out = os.path.abspath(out_dir)
        self.log = log
        self.threads = max(1, threads)
        self.state = State(os.path.join(self.out, ".drive-exporter", "estado.sqlite"))
        self.results = {}          # id(entry) -> (estado, nota)
        self._lock = threading.Lock()
        self._done = 0
        self._total = 0

    def abs(self, rel: str) -> str:
        return os.path.join(self.out, *rel.split("/"))

    # ---------- ejecución ----------
    def run(self, entries, dry_run=False):
        for e in entries:
            if e.kind == "skip":
                self.results[id(e)] = (STATUS_SKIP, e.note)
            elif e.kind == "dup":
                self.results[id(e)] = (STATUS_DUP, e.note)
            elif e.kind == "folder":
                self.results[id(e)] = (STATUS_FOLDER, "")
        tasks = [e for e in entries if e.kind in ("download", "export")]
        if dry_run:
            for e in tasks:
                self.results[id(e)] = (STATUS_DRY, "")
            return self.results

        for e in entries:
            if e.kind == "folder":
                os.makedirs(long_path(self.abs(e.local)), exist_ok=True)

        self._total = len(tasks)
        self.log(f"⬇️  {self._total} archivos a revisar/descargar con {self.threads} hilos")
        try:
            if self.threads == 1:
                for e in tasks:
                    self._process(e)
            else:
                with ThreadPoolExecutor(max_workers=self.threads) as pool:
                    futures = [pool.submit(self._process, e) for e in tasks]
                    for f in as_completed(futures):
                        f.result()
        except KeyboardInterrupt:
            self.log("\n⏸️  Interrumpido. Lo descargado se ha guardado: vuelve a ejecutar para seguir.")
            raise

        # Fechas de las carpetas: de dentro hacia fuera, después de escribir su contenido
        folders = sorted((e for e in entries if e.kind == "folder"),
                         key=lambda e: e.local.count("/"), reverse=True)
        for e in folders:
            apply_times(long_path(self.abs(e.local)), e.item.get("createdTime"),
                        e.item.get("modifiedTime"))

        self.state.close()
        return self.results

    def _tick(self, e, status, note=""):
        with self._lock:
            self._done += 1
            self.results[id(e)] = (status, note)
            icon = {STATUS_OK: "✓", STATUS_SAME: "=", STATUS_MOVED: "↪", STATUS_ERROR: "✗"}.get(status, "·")
            msg = f"[{self._done}/{self._total}] {icon} {e.local}"
            if note:
                msg += f"  ({note})"
            self.log(msg)

    def _process(self, e):
        item = e.item
        modified = item.get("modifiedTime", "")
        md5 = item.get("md5Checksum", "")
        target = self.abs(e.local)
        prev = self.state.get(e.key)

        if prev and prev["estado"] == "ok" and prev["modificado"] == modified \
                and (not md5 or prev["md5"] == md5):
            prev_abs = self.abs(prev["ruta_local"])
            if prev["ruta_local"] == e.local and os.path.exists(long_path(target)):
                self._tick(e, STATUS_SAME)
                return
            if prev["ruta_local"] != e.local and os.path.exists(long_path(prev_abs)) \
                    and not os.path.exists(long_path(target)):
                os.makedirs(long_path(os.path.dirname(target)), exist_ok=True)
                os.replace(long_path(prev_abs), long_path(target))
                self.state.mark(e.key, e.file_id, e.local, modified, md5, e.size, "ok")
                self._tick(e, STATUS_MOVED, f"antes en {prev['ruta_local']}")
                return

        part = target + ".part"
        try:
            os.makedirs(long_path(os.path.dirname(target)), exist_ok=True)
            with open(long_path(part), "wb") as fh:
                if e.kind == "download":
                    self.client.download(e.file_id, fh)
                else:
                    link = (item.get("exportLinks") or {}).get(e.export_mime)
                    self.client.export(e.file_id, e.export_mime, fh, export_link=link)
            if e.kind == "download" and md5:
                got = _md5(part)
                if got != md5:
                    raise IOError(f"La suma MD5 no coincide (Drive {md5}, local {got})")
            os.replace(long_path(part), long_path(target))
            apply_times(long_path(target), item.get("createdTime"), modified)
            size = os.path.getsize(long_path(target))
            self.state.mark(e.key, e.file_id, e.local, modified, md5, size, "ok")
            self._tick(e, STATUS_OK)
        except Exception as err:  # se registra y se sigue con el resto
            try:
                if os.path.exists(long_path(part)):
                    os.remove(long_path(part))
            except OSError:
                pass
            reason = getattr(err, "reason", "")
            note = _friendly_error(err, reason)
            self.state.mark(e.key, e.file_id, e.local, modified, md5, e.size, "error", note)
            self._tick(e, STATUS_ERROR, note)


def _friendly_error(err, reason: str) -> str:
    msgs = {
        "exportSizeLimitExceeded": "Demasiado grande para exportar (límite de Google)",
        "cannotDownloadAbusiveFile": "Google lo ha marcado como posible malware y no deja bajarlo",
        "fileNotDownloadable": "Este tipo de archivo no se puede descargar",
        "network": "Error de red persistente",
    }
    if reason in msgs:
        return msgs[reason]
    text = str(err).splitlines()[0] if str(err) else err.__class__.__name__
    return text[:200]
