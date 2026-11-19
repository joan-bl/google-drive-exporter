"""Construye el plan: qué se descarga, con qué nombre y en qué carpeta local.

En vez de recorrer Drive carpeta a carpeta (miles de peticiones), se pide la lista
completa de archivos de una vez y el árbol se reconstruye en memoria.
"""

from collections import defaultdict
from dataclasses import dataclass, field
import posixpath

from . import formats
from .names import NameRegistry, sanitize, with_extension

SEC_MY_DRIVE = "Mi unidad"
SEC_SHARED_WITH_ME = "Compartido conmigo"
SEC_SHARED_DRIVES = "Unidades compartidas"
SEC_NO_FOLDER = "Mi unidad (sin carpeta)"

SOURCES = {
    "mi-unidad": (SEC_MY_DRIVE, SEC_NO_FOLDER),
    "compartido": (SEC_SHARED_WITH_ME,),
    "unidades": (SEC_SHARED_DRIVES,),
}


@dataclass
class Entry:
    kind: str              # folder | download | export | skip | dup
    file_id: str
    name: str              # nombre en Drive
    mime: str
    section: str
    drive_path: str        # ruta tal como se ve en Drive
    local: str = ""        # ruta local relativa a la carpeta de salida (con "/")
    ext: str = ""          # extensión de exportación ("" para descargas normales)
    export_mime: str = ""
    item: dict = field(default_factory=dict, repr=False)
    note: str = ""
    dup_of: str = ""       # para kind == dup: ruta local donde ya se descargó

    @property
    def key(self) -> str:
        return f"{self.file_id}:{self.ext}" if self.ext else self.file_id

    @property
    def size(self) -> int:
        try:
            return int(self.item.get("size") or 0)
        except (TypeError, ValueError):
            return 0


@dataclass
class Options:
    sources: tuple = ("mi-unidad", "compartido", "unidades")
    formats: dict = None
    only_google: bool = False
    layout: str = "carpetas"       # carpetas | fecha
    shortcuts: str = "seguir"      # seguir | ignorar
    folder_id: str = None          # exportar solo esta carpeta
    # Carpetas (o archivos) que se quedan en Drive sin descargar. Un nombre suelto
    # ("w") se refiere a lo que está en el primer nivel de una sección (Mi unidad,
    # Compartido conmigo…); para algo más profundo, la ruta de Drive ("Mi unidad/Practiques/2020").
    exclude: tuple = ()


def _sort_key(item):
    return (item.get("createdTime") or "", item.get("id"))


def _section_root(section: str) -> str:
    return section.split("/")[0]


class Planner:
    def __init__(self, client, options: Options, log=print):
        self.client = client
        self.opt = options
        if self.opt.formats is None:
            self.opt.formats = formats.parse_format_args({})
        self.log = log
        self.items = {}
        self.children = defaultdict(list)
        self.placed = {}       # id -> ruta local donde quedó (para duplicados)
        self.visited = set()
        self.names = NameRegistry()
        self.entries = []

    # ---------- recogida de datos ----------
    def collect(self):
        self.log("🔍 Pidiendo a Drive la lista de archivos...")
        n = 0
        for f in self.client.list_files():
            self.items[f["id"]] = f
            n += 1
            if n % 2000 == 0:
                self.log(f"   {n} archivos listados...")
        self.log(f"   {n} archivos en Mi unidad y Compartido conmigo")
        self.root_id = self.client.root_id()
        self.shared_drives = []
        if "unidades" in self.opt.sources or self.opt.folder_id:
            for d in self.client.list_shared_drives():
                count = 0
                for f in self.client.list_files(drive_id=d["id"]):
                    self.items[f["id"]] = f
                    count += 1
                self.shared_drives.append(d)
                self.log(f"   {count} archivos en la unidad compartida '{d['name']}'")
        for it in self.items.values():
            for p in it.get("parents") or []:
                self.children[p].append(it)
        for lst in self.children.values():
            lst.sort(key=_sort_key)

    # ---------- plan ----------
    def build(self):
        self.collect()
        return self.place()

    def top_folders(self):
        """Carpetas del primer nivel de Mi unidad: [(nombre, archivos, bytes)], para elegir cuáles excluir."""
        def walk(fid):
            n, b = 0, 0
            for c in self.children.get(fid, []):
                if c.get("mimeType") == formats.FOLDER:
                    cn, cb = walk(c["id"])
                    n, b = n + cn, b + cb
                else:
                    n += 1
                    try:
                        b += int(c.get("size") or 0)
                    except (TypeError, ValueError):
                        pass
            return n, b
        out = []
        for c in self.children.get(self.root_id, []):
            if c.get("mimeType") == formats.FOLDER:
                n, b = walk(c["id"])
                out.append((c.get("name", ""), n, b))
        return sorted(out, key=lambda x: x[0].lower())

    def place(self):
        """Decide dónde va cada cosa (se puede repetir con otras opciones sin volver a listar Drive)."""
        self.placed, self.visited, self.names, self.entries = {}, set(), NameRegistry(), []
        self.excluded = {}     # id -> ruta de Drive de la exclusión que lo cubre
        if self.opt.folder_id:
            self._plan_single_folder(self.opt.folder_id)
        else:
            self._walk_children(self.root_id, SEC_MY_DRIVE, SEC_MY_DRIVE, SEC_MY_DRIVE)
            for d in sorted(self.shared_drives, key=lambda d: d["name"].lower()):
                name = sanitize(d["name"])
                sec = f"{SEC_SHARED_DRIVES}/{name}"
                self._walk_children(d["id"], sec, sec, sec)
            self.visited.add(self.root_id)
            # Lo que no cuelga de Mi unidad ni de una unidad compartida: "Compartido conmigo"
            # (si no es tuyo) o "sin carpeta" (si es tuyo). Si un acceso directo ya lo trajo,
            # _place lo anota como repetido.
            leftovers = sorted(self.items.values(), key=_sort_key)
            known = set(self.items) | {self.root_id} | {d["id"] for d in self.shared_drives}
            for it in leftovers:
                parents = it.get("parents") or []
                if any(p in known for p in parents):
                    continue  # se recorrerá desde su carpeta padre
                section = SEC_NO_FOLDER if it.get("ownedByMe") else SEC_SHARED_WITH_ME
                self._place(it, section, section, section)
        wanted = self._wanted_sections()
        if wanted is not None:
            self.entries = [e for e in self.entries if _section_root(e.section) in wanted]
        return self.entries

    def _wanted_sections(self):
        if self.opt.folder_id:
            return None
        wanted = set()
        for s in self.opt.sources:
            wanted.update(SOURCES[s])
        return wanted

    def _plan_single_folder(self, folder_id):
        folder = self.items.get(folder_id) or self.client.get_file(folder_id)
        if not folder:
            raise SystemExit(f"No encuentro la carpeta {folder_id} o no tienes acceso.")
        if folder["mimeType"] != formats.FOLDER:
            self._place(folder, "Carpeta", "Carpeta", "Carpeta")
            return
        if folder_id not in self.items:
            # carpeta fuera de la lista (p. ej. de una unidad a la que no perteneces)
            self.items[folder_id] = folder
            for f in self.client.list_children(folder_id):
                self.items[f["id"]] = f
                self.children[folder_id].append(f)
        name = sanitize(folder["name"])
        self._walk_children(folder_id, name, name, name)

    def _walk_children(self, parent_id, section, drive_dir, local_dir):
        for child in self.children.get(parent_id, []):
            self._place(child, section, drive_dir, local_dir)

    def _local_dir_for_file(self, section, local_dir, item):
        if self.opt.layout != "fecha":
            return local_dir
        mod = (item.get("modifiedTime") or item.get("createdTime") or "0000-00")[:7]
        year = mod[:4]
        return f"{section}/{year}/{mod}"

    def _excluded(self, item, section, drive_dir, name, drive_path):
        for pat in self.opt.exclude or ():
            p = pat.strip().strip("/").lower()
            if not p:
                continue
            if p == item.get("id", "").lower() or p == drive_path.lower():
                return True
            if "/" not in p and drive_dir == section and name.lower() == p:
                return True
        return False

    def _mark_excluded(self, item, where, depth=0):
        """Marca como excluido todo lo que cuelga de item, incluido aquello a lo que apuntan
        sus accesos directos (si no, aparecería otra vez en «Compartido conmigo»)."""
        fid = item["id"]
        if fid in self.excluded or depth > 50:
            return
        self.excluded[fid] = where
        if item.get("mimeType") == formats.SHORTCUT:
            target = self.items.get((item.get("shortcutDetails") or {}).get("targetId"))
            if target:
                self._mark_excluded(target, where, depth + 1)
        for child in self.children.get(fid, []):
            self._mark_excluded(child, where, depth + 1)

    def _place(self, item, section, drive_dir, local_dir, display_name=None):
        """Añade al plan un archivo o carpeta (y su contenido) en local_dir."""
        fid = item["id"]
        mime = item.get("mimeType", "")
        name = display_name or item.get("name") or "sin nombre"
        drive_path = f"{drive_dir}/{name}"

        if self._excluded(item, section, drive_dir, name, drive_path):
            # Ni se descarga ni se toca: su contenido tampoco se recorre
            self.visited.add(fid)
            self._mark_excluded(item, drive_path)
            self.entries.append(Entry("skip", fid, name, mime, section, drive_path, item=item,
                                      note="Excluida por ti: se queda en Drive"))
            return
        if fid in self.excluded:
            self.visited.add(fid)
            self.entries.append(Entry("skip", fid, name, mime, section, drive_path, item=item,
                                      note=f"Se queda en Drive: está dentro de lo que excluiste ({self.excluded[fid]})"))
            return

        if mime == formats.SHORTCUT:
            self.visited.add(fid)
            return self._place_shortcut(item, section, drive_dir, local_dir, drive_path)

        if fid in self.placed:
            self.entries.append(Entry("dup", fid, name, mime, section, drive_path, item=item,
                                      dup_of=self.placed[fid],
                                      note=f"Ya incluido en {self.placed[fid]}"))
            return
        self.visited.add(fid)

        if mime == formats.FOLDER:
            if self.opt.layout == "fecha":
                folder_local = local_dir
                self.placed[fid] = folder_local
            else:
                folder_name = self.names.reserve(local_dir, sanitize(name))
                folder_local = f"{local_dir}/{folder_name}"
                self.placed[fid] = folder_local
                self.entries.append(Entry("folder", fid, name, mime, section, drive_path,
                                          local=folder_local, item=item))
            self._walk_children(fid, section, drive_path, folder_local)
            return

        file_dir = self._local_dir_for_file(section, local_dir, item)
        if mime in formats.NOT_EXPORTABLE:
            self.entries.append(Entry("skip", fid, name, mime, section, drive_path, item=item,
                                      note=formats.NOT_EXPORTABLE[mime]))
            self.placed[fid] = drive_path
            return

        if formats.is_google_file(mime):
            targets = formats.export_targets(item, self.opt.formats)
            if not targets:
                self.entries.append(Entry("skip", fid, name, mime, section, drive_path, item=item,
                                          note="Tipo de Google sin formato de exportación"))
                self.placed[fid] = drive_path
                return
            first = None
            for ext, emime in targets:
                fname = self.names.reserve(file_dir, sanitize(with_extension(name, ext)))
                local = f"{file_dir}/{fname}"
                first = first or local
                self.entries.append(Entry("export", fid, name, mime, section, drive_path, local=local,
                                          ext=ext, export_mime=emime, item=item))
            self.placed[fid] = first
            return

        if self.opt.only_google:
            self.placed[fid] = drive_path
            return  # modo antiguo: los archivos normales no se descargan
        caps = item.get("capabilities") or {}
        if caps.get("canDownload") is False:
            self.entries.append(Entry("skip", fid, name, mime, section, drive_path, item=item,
                                      note="El propietario ha desactivado la descarga"))
            self.placed[fid] = drive_path
            return
        fname = self.names.reserve(file_dir, sanitize(name))
        local = f"{file_dir}/{fname}"
        self.placed[fid] = local
        self.entries.append(Entry("download", fid, name, mime, section, drive_path, local=local,
                                  item=item))

    def _place_shortcut(self, item, section, drive_dir, local_dir, drive_path):
        details = item.get("shortcutDetails") or {}
        target_id = details.get("targetId")
        wanted = self._wanted_sections()
        if self.opt.shortcuts == "ignorar" or (wanted is not None and _section_root(section) not in wanted):
            # En secciones que no se exportan no se siguen los accesos directos: si no,
            # "reclamarían" carpetas que sí se quieren exportar en otra sección.
            self.entries.append(Entry("skip", item["id"], item["name"], item["mimeType"], section,
                                      drive_path, item=item, note="Acceso directo (no se sigue)"))
            return
        target = self.items.get(target_id)
        if target is None and target_id:
            target = self.client.get_file(target_id)
            if target:
                self.items[target_id] = target
                if target.get("mimeType") == formats.FOLDER:
                    for f in self.client.list_children(target_id):
                        if f["id"] not in self.items:
                            self.items[f["id"]] = f
                            self.children[target_id].append(f)
                    self.children[target_id].sort(key=_sort_key)
        if not target:
            self.entries.append(Entry("skip", item["id"], item["name"], item["mimeType"], section,
                                      drive_path, item=item,
                                      note="Acceso directo roto (el original no existe o no tienes acceso)"))
            return
        # El acceso directo se convierte en el archivo/carpeta real, con el nombre del acceso.
        self._place(target, section, drive_dir, local_dir, display_name=item.get("name"))


def summarize(entries):
    """Resumen por sección para mostrar antes de descargar."""
    out = defaultdict(lambda: {"carpetas": 0, "descargas": 0, "exportaciones": 0,
                               "omitidos": 0, "duplicados": 0, "bytes": 0})
    for e in entries:
        s = out[_section_root(e.section)]
        if e.kind == "folder":
            s["carpetas"] += 1
        elif e.kind == "download":
            s["descargas"] += 1
            s["bytes"] += e.size
        elif e.kind == "export":
            s["exportaciones"] += 1
        elif e.kind == "skip":
            s["omitidos"] += 1
        elif e.kind == "dup":
            s["duplicados"] += 1
    return dict(out)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def local_parent(path: str) -> str:
    return posixpath.dirname(path)
