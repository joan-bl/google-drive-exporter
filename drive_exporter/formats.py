"""Tipos de archivo de Google y a qué formatos se pueden exportar."""

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
GOOGLE_PREFIX = "application/vnd.google-apps."

# Formatos de exportación conocidos: extensión -> tipo MIME
EXPORT_MIMES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "epub": "application/epub+zip",
    "html.zip": "application/zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ods": "application/x-vnd.oasis.opendocument.spreadsheet",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "png": "image/png",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
    "json": "application/vnd.google-apps.script+json",
    "mp4": "video/mp4",
}

# Clave corta que usa el usuario -> tipo de Google
KINDS = {
    "doc": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "slides": "application/vnd.google-apps.presentation",
    "drawing": "application/vnd.google-apps.drawing",
    "script": "application/vnd.google-apps.script",
    "jam": "application/vnd.google-apps.jam",
    "vid": "application/vnd.google-apps.vid",
}

# Formatos por defecto de cada tipo
DEFAULT_FORMATS = {
    "doc": ["docx"],
    "sheet": ["xlsx"],
    "slides": ["pptx"],
    "drawing": ["png"],
    "script": ["json"],
    "jam": ["pdf"],
    "vid": ["mp4"],
}

# Formatos válidos de cada tipo (lo que acepta la API de Drive)
ALLOWED_FORMATS = {
    "doc": ["docx", "odt", "rtf", "pdf", "txt", "md", "epub", "html.zip"],
    "sheet": ["xlsx", "ods", "pdf", "csv", "tsv", "html.zip"],
    "slides": ["pptx", "odp", "pdf", "txt", "png", "jpg", "svg"],
    "drawing": ["png", "jpg", "svg", "pdf"],
    "script": ["json"],
    "jam": ["pdf"],
    "vid": ["mp4"],
}

# Tipos de Google que no se pueden descargar por la API, con una explicación
NOT_EXPORTABLE = {
    "application/vnd.google-apps.form": "Los formularios no se pueden exportar. Las respuestas suelen estar en una Hoja de cálculo vinculada.",
    "application/vnd.google-apps.site": "Los Google Sites no se pueden exportar por la API.",
    "application/vnd.google-apps.map": "Los mapas de My Maps no se pueden exportar por la API (se puede descargar un KML desde la web).",
    "application/vnd.google-apps.fusiontable": "Fusion Tables ya no existe.",
}

KIND_BY_MIME = {mime: kind for kind, mime in KINDS.items()}


def is_google_file(mime: str) -> bool:
    return mime.startswith(GOOGLE_PREFIX) and mime not in (FOLDER, SHORTCUT)


def parse_format_args(overrides: dict) -> dict:
    """Combina los formatos por defecto con los que pide el usuario.

    overrides: {"doc": "docx,pdf", ...}. Lanza ValueError si un formato no vale.
    """
    result = {k: list(v) for k, v in DEFAULT_FORMATS.items()}
    for kind, value in overrides.items():
        if not value:
            continue
        fmts = [f.strip().lower().lstrip(".") for f in value.split(",") if f.strip()]
        bad = [f for f in fmts if f not in ALLOWED_FORMATS[kind]]
        if bad:
            raise ValueError(
                f"Formato no válido para {kind}: {', '.join(bad)}. "
                f"Opciones: {', '.join(ALLOWED_FORMATS[kind])}"
            )
        result[kind] = fmts
    return result


def export_targets(item: dict, formats: dict) -> list:
    """Devuelve [(extensión, mime)] a los que hay que exportar un archivo de Google.

    Si el tipo no es conocido pero Drive ofrece exportLinks, usa el primero.
    """
    mime = item.get("mimeType", "")
    kind = KIND_BY_MIME.get(mime)
    if kind:
        return [(ext, EXPORT_MIMES[ext]) for ext in formats[kind]]
    links = item.get("exportLinks") or {}
    if links:
        ext_by_mime = {v: k for k, v in EXPORT_MIMES.items()}
        for m in links:
            if m in ext_by_mime:
                return [(ext_by_mime[m], m)]
        m = next(iter(links))
        return [(m.split("/")[-1].split("+")[0].split(".")[-1], m)]
    return []
