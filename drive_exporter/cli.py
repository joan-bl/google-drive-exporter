"""Línea de comandos: python -m drive_exporter [opciones]"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

from . import __version__, formats
from .planner import Options, Planner, SOURCES, human_size, summarize

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


class Logger:
    def __init__(self):
        self._fh = None

    def open(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")
        self._fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")

    def __call__(self, msg):
        print(msg, flush=True)
        if self._fh:
            self._fh.write(msg + "\n")
            self._fh.flush()


def folder_id_from(value: str) -> str:
    """Acepta un ID o una URL de Drive y devuelve el ID."""
    m = re.search(r"/folders/([\w-]+)", value) or re.search(r"[?&]id=([\w-]+)", value) \
        or re.search(r"/d/([\w-]+)", value)
    return m.group(1) if m else value.strip()


CONFIG_FILE = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "drive-exporter", "config.json")


def _load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


def _looks_like_credentials(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return isinstance(data, dict) and ("installed" in data or "web" in data)
    except (OSError, ValueError):
        return False


def find_credentials(path, interactive=False):
    """Busca credentials.json: opción --credenciales, la ruta recordada, la carpeta actual
    y la del programa. Si no está y hay alguien delante, lo pide una vez y lo recuerda."""
    if path:
        return path
    remembered = _load_config().get("credenciales")
    cands = [remembered] if remembered else []
    cands += [os.path.join(os.getcwd(), "credentials.json"), os.path.join(HERE, "credentials.json")]
    for cand in cands:
        if cand and os.path.exists(cand):
            return cand
    if interactive:
        print("\nNo encuentro tus credenciales de Google (credentials.json).")
        print("Arrastra el archivo a esta ventana (o pega su ruta) y pulsa Enter.")
        print("Solo se pide una vez: la ruta queda guardada en " + CONFIG_FILE)
        while True:
            given = input("credentials.json: ").strip().strip('"').strip("'").strip()
            if not given:
                break
            if os.path.isdir(given):
                given = os.path.join(given, "credentials.json")
            if _looks_like_credentials(given):
                cfg = _load_config()
                cfg["credenciales"] = os.path.abspath(given)
                _save_config(cfg)
                return os.path.abspath(given)
            print("Ese archivo no parece un credentials.json de Google (descárgalo de Google Cloud: ver README). Prueba otra vez o pulsa Enter para salir.")
    return os.path.join(os.getcwd(), "credentials.json")


def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m drive_exporter",
        description="Copia todo tu Google Drive al ordenador: Mi unidad, Compartido conmigo y "
                    "unidades compartidas, convirtiendo Docs/Hojas/Presentaciones a formatos "
                    "normales y respetando carpetas y fechas.",
    )
    p.add_argument("--version", action="version", version=f"drive_exporter {__version__}")
    p.add_argument("-o", "--salida", default="exports", help="carpeta donde se guarda todo (por defecto: exports)")
    p.add_argument("--origen", action="append", choices=list(SOURCES),
                   help="qué exportar; se puede repetir. Por defecto: todo (mi-unidad, compartido, unidades)")
    p.add_argument("--carpeta", help="exportar solo esta carpeta (ID o enlace de Drive)")
    g = p.add_argument_group("formatos de los archivos de Google (separados por comas)")
    for kind in ("doc", "sheet", "slides", "drawing"):
        g.add_argument(f"--{kind}", help=f"por defecto {','.join(formats.DEFAULT_FORMATS[kind])}; "
                                         f"opciones: {','.join(formats.ALLOWED_FORMATS[kind])}")
    p.add_argument("--solo-google", action="store_true",
                   help="exportar solo Docs/Hojas/Presentaciones y no bajar PDFs, fotos, etc.")
    p.add_argument("--orden", choices=["carpetas", "fecha"], default="carpetas",
                   help="carpetas: igual que en Drive (por defecto). fecha: Sección/AAAA/AAAA-MM/")
    p.add_argument("--accesos-directos", choices=["seguir", "ignorar"], default="seguir",
                   help="seguir: bajar el archivo o carpeta al que apunta (por defecto)")
    p.add_argument("--hilos", type=int, default=4, help="descargas en paralelo (por defecto 4)")
    p.add_argument("--simular", action="store_true",
                   help="no descarga nada: solo muestra qué haría y genera el índice")
    p.add_argument("--credenciales", help="ruta a credentials.json")
    p.add_argument("--sin-navegador", action="store_true",
                   help="no abrir el navegador al dar permiso: muestra el enlace para copiarlo")
    p.add_argument("--mandar-a-papelera", action="store_true",
                   help="PELIGROSO: tras exportar, manda a la papelera de Drive los Docs/Hojas/"
                        "Presentaciones tuyos exportados sin error (recuperables 30 días)")
    p.add_argument("-s", "--si", action="store_true", help="no preguntar antes de empezar")
    return p


def wizard(args):
    """Preguntas sencillas cuando se ejecuta sin opciones (doble clic en el .bat)."""
    print("\n📦 Google Drive Exporter: asistente\n")
    print("¿Qué quieres exportar?")
    print("  1) Todo (Mi unidad + Compartido conmigo + Unidades compartidas)  [recomendado]")
    print("  2) Solo Mi unidad")
    print("  3) Solo Compartido conmigo")
    print("  4) Una carpeta concreta")
    choice = input("Elige [1]: ").strip() or "1"
    if choice == "2":
        args.origen = ["mi-unidad"]
    elif choice == "3":
        args.origen = ["compartido"]
    elif choice == "4":
        args.carpeta = input("Pega el enlace o el ID de la carpeta: ").strip()
    out = input(f"¿Dónde lo guardo? [{args.salida}]: ").strip().strip('"')
    if out:
        args.salida = out
    order = input("¿Ordenar como en Drive (1) o por fecha AAAA/AAAA-MM (2)? [1]: ").strip()
    if order == "2":
        args.orden = "fecha"
    sim = input("¿Hacer primero una simulación sin descargar nada? (s/N): ").strip().lower()
    args.simular = sim.startswith("s")
    return args


def main(argv=None):
    _setup_console()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(argv)
    if not argv and sys.stdin.isatty():
        args = wizard(args)

    try:
        fmt = formats.parse_format_args({k: getattr(args, k) for k in ("doc", "sheet", "slides", "drawing")})
    except ValueError as err:
        parser.error(str(err))

    out_dir = os.path.abspath(args.salida)
    log = Logger()
    log.open(os.path.join(out_dir, ".drive-exporter", "registro.log"))

    from .api import SCOPE_FULL, SCOPE_READONLY, DriveClient, authenticate
    creds_file = find_credentials(args.credenciales, interactive=sys.stdin.isatty())
    creds_dir = os.path.dirname(os.path.abspath(creds_file))
    if args.mandar_a_papelera:
        scopes, token = [SCOPE_FULL], os.path.join(creds_dir, "token_escritura.json")
    else:
        scopes, token = [SCOPE_READONLY], os.path.join(creds_dir, "token_lectura.json")

    log("🔐 Conectando con Google Drive" + (" (solo lectura)" if not args.mandar_a_papelera else " (con permiso de escritura)"))
    try:
        creds = authenticate(creds_file, token, scopes, open_browser=not args.sin_navegador)
    except FileNotFoundError as err:
        log(f"❌ {err}")
        return 2
    client = DriveClient(creds, log=log)
    who = client.about().get("user", {})
    log(f"✅ Cuenta: {who.get('displayName', '')} <{who.get('emailAddress', '')}>")

    opts = Options(
        sources=tuple(args.origen or SOURCES.keys()),
        formats=fmt,
        only_google=args.solo_google,
        layout=args.orden,
        shortcuts=args.accesos_directos,
        folder_id=folder_id_from(args.carpeta) if args.carpeta else None,
    )
    planner = Planner(client, opts, log=log)
    entries = planner.build()
    summary = summarize(entries)

    log("\n📋 Plan")
    for sec, s in summary.items():
        log(f"  {sec}: {s['descargas']} archivos ({human_size(s['bytes'])}), "
            f"{s['exportaciones']} exportaciones de Google, {s['carpetas']} carpetas"
            + (f", {s['omitidos']} omitidos" if s["omitidos"] else "")
            + (f", {s['duplicados']} repetidos" if s["duplicados"] else ""))
    if not entries:
        log("  (nada que exportar)")

    from .exporter import Exporter
    from .report import write_reports

    if args.mandar_a_papelera and not args.simular:
        log("\n⚠️  Has pedido mandar a la papelera de Drive los originales exportados.")
        if input("Escribe SI para confirmarlo: ").strip() != "SI":
            log("Cancelado.")
            return 1

    if not args.simular and not args.si and sys.stdin.isatty():
        if input(f"\n¿Empezar a descargar en {out_dir}? (S/n): ").strip().lower().startswith("n"):
            log("Cancelado.")
            return 1

    exporter = Exporter(client, out_dir, log=log, threads=args.hilos,
                        trash_originals=args.mandar_a_papelera and not args.simular)
    results = exporter.run(entries, dry_run=args.simular)
    title = f"Exportación de Drive · {who.get('emailAddress', '')} · {datetime.now():%d/%m/%Y %H:%M}"
    csv_path, html_path = write_reports(out_dir, entries, results, summary, title)

    counts = {}
    for st, _ in results.values():
        counts[st] = counts.get(st, 0) + 1
    log("\n🎉 Terminado" if not args.simular else "\n🧪 Simulación terminada (no se ha descargado nada)")
    log("   " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    log(f"📁 Carpeta: {out_dir}")
    log(f"📑 Índice: {html_path}")
    errors = counts.get("error", 0)
    if errors:
        log(f"⚠️  {errors} con error: vuelve a ejecutar para reintentarlos, o mira el informe.")
    return 0 if not errors else 3
