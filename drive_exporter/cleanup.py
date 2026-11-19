"""Después de exportar: mandar a la papelera de Drive lo que ya tienes en tu ordenador.

Reglas de seguridad:
- Solo lo que es **tuyo**. Lo de otras personas (Compartido conmigo) y lo de las unidades
  compartidas no se toca.
- Solo lo que se ha descargado o exportado **sin errores** (todas sus copias locales).
- Antes de mandar cada archivo a la papelera se vuelve a consultar en Drive: si ha cambiado
  desde que se descargó, se deja donde está.
- Una carpeta solo va a la papelera si **todo** lo que contiene se ha mandado también
  (si no, mandarla arrastraría cosas que no tienes en el ordenador).
- Es la papelera, no un borrado: Google la vacía a los 30 días y hasta entonces se recupera.
"""

from dataclasses import dataclass, field

from .exporter import STATUS_MOVED, STATUS_OK, STATUS_SAME

DONE = {STATUS_OK, STATUS_SAME, STATUS_MOVED}


@dataclass
class TrashPlan:
    files: list = field(default_factory=list)      # [(file_id, drive_path, modifiedTime, size)]
    folders: list = field(default_factory=list)    # [(folder_id, drive_path)], de dentro hacia fuera
    kept: dict = field(default_factory=dict)       # motivo -> número de elementos que se quedan

    @property
    def size(self):
        return sum(s for *_, s in self.files)


def _keep(plan, reason):
    plan.kept[reason] = plan.kept.get(reason, 0) + 1


def plan_trash(entries, results, assume_ok=False):
    """Decide qué se puede mandar a la papelera a partir del plan y del resultado de la exportación.
    assume_ok: para la simulación, da por bien descargado todo lo que se iba a descargar."""
    plan = TrashPlan()
    by_id = {}
    for e in entries:
        if e.kind in ("download", "export"):
            by_id.setdefault(e.file_id, []).append(e)

    trashed_paths = set()   # rutas de Drive de lo que se va a la papelera
    blocked_paths = []      # rutas de Drive que impiden mandar su carpeta

    for fid, group in by_id.items():
        e = group[0]
        item = e.item
        ok = assume_ok or all(results.get(id(x), ("",))[0] in DONE for x in group)
        if item.get("driveId"):
            _keep(plan, "está en una unidad compartida")
        elif not item.get("ownedByMe"):
            _keep(plan, "es de otra persona")
        elif not ok:
            _keep(plan, "no se descargó bien")
        elif (item.get("capabilities") or {}).get("canTrash") is False:
            _keep(plan, "Drive no deja mandarlo a la papelera")
        else:
            plan.files.append((fid, e.drive_path, item.get("modifiedTime", ""), e.size))
            trashed_paths.add(e.drive_path)
            continue
        blocked_paths.append(e.drive_path)

    for e in entries:
        if e.kind in ("skip", "dup"):
            blocked_paths.append(e.drive_path)
            if e.kind == "dup":
                _keep(plan, "está repetido en otro sitio")
            elif "xclu" in e.note:
                _keep(plan, "lo excluiste (se queda en Drive)")
            else:
                _keep(plan, "no se puede descargar (formulario, acceso directo roto…)")

    folders = [e for e in entries if e.kind == "folder"]
    folders.sort(key=lambda e: e.drive_path.count("/"), reverse=True)
    for f in folders:
        prefix = f.drive_path + "/"
        blocked = any(p.startswith(prefix) for p in blocked_paths)
        if blocked or f.item.get("driveId") or not f.item.get("ownedByMe"):
            blocked_paths.append(f.drive_path)
            continue
        plan.folders.append((f.file_id, f.drive_path))
        trashed_paths.add(f.drive_path)
    return plan


def run_trash(client, plan, log=print):
    """Manda a la papelera lo del plan. Devuelve (mandados, saltados)."""
    sent, skipped = 0, 0
    sent_paths = set()
    for fid, path, modified, _size in plan.files:
        current = client.get_file(fid)
        if current is None:
            log(f"   · ya no está en Drive: {path}")
            continue
        if current.get("trashed"):
            sent_paths.add(path)
            continue
        if modified and current.get("modifiedTime") != modified:
            log(f"   ⚠ ha cambiado desde que se descargó, se queda: {path}")
            skipped += 1
            continue
        try:
            client.trash(fid)
            sent += 1
            sent_paths.add(path)
            log(f"   🗑 {path}")
        except Exception as err:  # noqa: BLE001
            skipped += 1
            log(f"   ⚠ no se pudo: {path} ({err})")
    # Carpetas: solo si todo lo de dentro se ha mandado de verdad
    failed = {p for _, p, *_ in plan.files if p not in sent_paths}
    for fid, path in plan.folders:
        if any(p.startswith(path + "/") for p in failed):
            failed.add(path)
            continue
        try:
            client.trash(fid)
            sent += 1
            log(f"   🗑 {path}/")
        except Exception as err:  # noqa: BLE001
            skipped += 1
            failed.add(path)
            log(f"   ⚠ no se pudo: {path}/ ({err})")
    return sent, skipped
