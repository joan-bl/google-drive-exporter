"""Nombres de archivo válidos en Windows, macOS y Linux, sin choques."""

import os
import re

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_COMPONENT = 150  # margen para que la ruta completa no pase de los límites de Windows


def split_ext(name: str):
    """Separa nombre y extensión. Trata 'html.zip' como una sola extensión."""
    lower = name.lower()
    if lower.endswith(".html.zip"):
        return name[:-9], name[-9:]
    base, ext = os.path.splitext(name)
    if len(ext) > 10 or " " in ext:  # "Informe v2. final" no tiene extensión real
        return name, ""
    return base, ext


def sanitize(name: str, fallback: str = "sin nombre") -> str:
    name = INVALID.sub("_", name or "")
    name = name.strip().rstrip(". ")
    if not name:
        name = fallback
    base, ext = split_ext(name)
    if base.upper() in RESERVED:
        base = base + "_"
    if len(base) + len(ext) > MAX_COMPONENT:
        base = base[: MAX_COMPONENT - len(ext)].rstrip(". ")
    return base + ext


def with_extension(name: str, ext: str) -> str:
    """Añade la extensión salvo que el nombre ya la tenga."""
    ext = "." + ext.lstrip(".")
    if name.lower().endswith(ext.lower()):
        return name
    return name + ext


class NameRegistry:
    """Reparte nombres únicos dentro de cada carpeta local.

    Windows no distingue mayúsculas, así que 'Foto.jpg' y 'foto.jpg' chocan:
    el segundo pasa a ser 'foto (2).jpg'.
    """

    def __init__(self):
        self._used = {}

    def reserve(self, folder: str, name: str) -> str:
        used = self._used.setdefault(folder.lower(), set())
        candidate = name
        base, ext = split_ext(name)
        n = 2
        while candidate.lower() in used:
            candidate = f"{base} ({n}){ext}"
            n += 1
        used.add(candidate.lower())
        return candidate

    def claim(self, folder: str, name: str) -> bool:
        """Intenta reservar exactamente ese nombre. Devuelve False si ya está cogido."""
        used = self._used.setdefault(folder.lower(), set())
        if name.lower() in used:
            return False
        used.add(name.lower())
        return True


def long_path(path: str) -> str:
    """En Windows, permite rutas de más de 260 caracteres."""
    if os.name != "nt":
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path
