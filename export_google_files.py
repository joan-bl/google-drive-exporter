"""Compatibilidad con la versión 1: ahora todo está en el paquete drive_exporter.

    python export_google_files.py [opciones]   ==   python -m drive_exporter [opciones]
"""
import sys

from drive_exporter.cli import main

if __name__ == "__main__":
    sys.exit(main())
