"""Poner a los archivos descargados las fechas que tenían en Drive."""

import os
from datetime import datetime, timezone


def parse_rfc3339(value: str):
    """'2024-03-05T10:20:30.123Z' -> datetime con zona horaria (o None)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _set_windows_creation_time(path: str, created: datetime) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    FILE_WRITE_ATTRIBUTES = 0x100
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # necesario para carpetas
    share = 0x1 | 0x2 | 0x4

    CreateFileW = kernel32.CreateFileW
    CreateFileW.restype = wintypes.HANDLE
    CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = CreateFileW(path, FILE_WRITE_ATTRIBUTES, share, None, OPEN_EXISTING,
                         FILE_FLAG_BACKUP_SEMANTICS, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return
    try:
        # FILETIME: intervalos de 100 ns desde el 1/1/1601
        ticks = int((created.timestamp() + 11644473600) * 10_000_000)
        ft = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
        kernel32.SetFileTime(handle, ctypes.byref(ft), None, None)
    finally:
        kernel32.CloseHandle(handle)


def apply_times(path: str, created: str = None, modified: str = None) -> None:
    """Fecha de modificación (todas las plataformas) y de creación (solo Windows)."""
    mod = parse_rfc3339(modified)
    if mod:
        ts = mod.timestamp()
        try:
            os.utime(path, (ts, ts))
        except OSError:
            pass
    cre = parse_rfc3339(created)
    if cre and os.name == "nt":
        try:
            _set_windows_creation_time(path, cre)
        except OSError:
            pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
