"""Estado de la exportación en una base SQLite, para reanudar y actualizar.

Por cada archivo exportado se guarda dónde quedó y qué versión se bajó
(modifiedTime y md5). Al volver a ejecutar solo se descarga lo nuevo o lo cambiado.
"""

import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    clave TEXT PRIMARY KEY,      -- id de Drive (+ ':ext' si es una exportación)
    id TEXT NOT NULL,
    ruta_local TEXT,
    modificado TEXT,
    md5 TEXT,
    tamano INTEGER,
    estado TEXT,                 -- ok | error
    error TEXT,
    actualizado TEXT
);
"""


class State:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            row = self._db.execute(
                "SELECT ruta_local, modificado, md5, tamano, estado, error FROM archivos WHERE clave = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return dict(zip(("ruta_local", "modificado", "md5", "tamano", "estado", "error"), row))

    def mark(self, key, file_id, local, modified, md5, size, status, error=""):
        from .timestamps import now_iso
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO archivos VALUES (?,?,?,?,?,?,?,?,?)",
                (key, file_id, local, modified, md5, size, status, error, now_iso()),
            )
            self._db.commit()

    def all_ok_paths(self):
        with self._lock:
            return {r[0]: r[1] for r in self._db.execute(
                "SELECT clave, ruta_local FROM archivos WHERE estado = 'ok'")}

    def close(self):
        with self._lock:
            self._db.close()
