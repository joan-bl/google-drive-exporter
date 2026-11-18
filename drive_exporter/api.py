"""Acceso a la API de Google Drive: autenticación, listados y descargas.

Todo lo que habla con Google está aquí, para poder probar el resto con un Drive falso
(ver tests/fake_drive.py), que implementa los mismos métodos que DriveClient.
"""

import os
import random
import threading
import time

SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
SCOPE_FULL = "https://www.googleapis.com/auth/drive"

FILE_FIELDS = (
    "id, name, mimeType, parents, createdTime, modifiedTime, size, md5Checksum, "
    "ownedByMe, owners(displayName, emailAddress), sharedWithMeTime, driveId, "
    "shortcutDetails(targetId, targetMimeType), capabilities(canDownload), "
    "webViewLink, exportLinks, trashed"
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError", "internalError"}


class DriveError(Exception):
    """Error de Drive con un motivo corto (p. ej. 'exportSizeLimitExceeded')."""

    def __init__(self, message, reason="", status=0):
        super().__init__(message)
        self.reason = reason
        self.status = status


def _http_error_info(err):
    """Saca (status, reason) de un HttpError de googleapiclient."""
    status = getattr(getattr(err, "resp", None), "status", 0) or 0
    reason = ""
    try:
        details = err.error_details or []
        if details and isinstance(details, list):
            reason = details[0].get("reason", "")
    except Exception:
        pass
    if not reason:
        text = str(err)
        for r in ("exportSizeLimitExceeded", "cannotDownloadAbusiveFile", "fileNotDownloadable",
                  *RETRYABLE_REASONS):
            if r in text:
                reason = r
                break
    return int(status), reason


def with_retries(func, *, attempts=6, base_delay=1.5, log=None):
    """Ejecuta func() con reintentos y espera exponencial ante errores temporales."""
    from googleapiclient.errors import HttpError

    for attempt in range(attempts):
        try:
            return func()
        except HttpError as err:
            status, reason = _http_error_info(err)
            temporary = status in RETRYABLE_STATUS or reason in RETRYABLE_REASONS
            if not temporary or attempt == attempts - 1:
                raise DriveError(str(err), reason, status) from err
        except (ConnectionError, TimeoutError, OSError) as err:
            if attempt == attempts - 1:
                raise DriveError(f"Error de red: {err}", "network") from err
        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        if log:
            log(f"  ⏳ Error temporal, reintento {attempt + 1}/{attempts - 1} en {delay:.0f} s")
        time.sleep(delay)


def authenticate(credentials_file, token_file, scopes, open_browser=True):
    """Devuelve credenciales válidas. La primera vez abre el navegador para dar permiso."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)
        if not set(scopes).issubset(set(creds.scopes or [])):
            creds = None  # el token guardado tiene otros permisos: pedir de nuevo
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not os.path.exists(credentials_file):
            raise FileNotFoundError(
                f"No encuentro '{credentials_file}'. Mira en el README cómo crear las "
                "credenciales de Google Cloud (paso 'Credenciales')."
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
        creds = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            authorization_prompt_message="Abre este enlace para dar permiso:\n{url}\n",
            success_message="Listo. Ya puedes cerrar esta pestaña y volver al programa.",
        )
    os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    return creds


class DriveClient:
    """Envoltorio de la API v3 de Drive. Seguro para usar desde varios hilos."""

    def __init__(self, creds, log=None):
        self._creds = creds
        self._local = threading.local()
        self._log = log

    @property
    def _svc(self):
        if not hasattr(self._local, "svc"):
            from googleapiclient.discovery import build
            self._local.svc = build("drive", "v3", credentials=self._creds, cache_discovery=False)
        return self._local.svc

    def _run(self, request_factory):
        return with_retries(lambda: request_factory().execute(), log=self._log)

    # ---------- información ----------
    def about(self) -> dict:
        res = self._run(lambda: self._svc.about().get(fields="user(displayName, emailAddress), storageQuota"))
        return res

    def root_id(self) -> str:
        return self._run(lambda: self._svc.files().get(fileId="root", fields="id"))["id"]

    def get_file(self, file_id: str):
        try:
            return self._run(lambda: self._svc.files().get(
                fileId=file_id, fields=FILE_FIELDS, supportsAllDrives=True))
        except DriveError as err:
            if err.status in (403, 404):
                return None
            raise

    def list_shared_drives(self) -> list:
        drives, token = [], None
        while True:
            res = self._run(lambda: self._svc.drives().list(
                pageSize=100, pageToken=token, fields="nextPageToken, drives(id, name)"))
            drives.extend(res.get("drives", []))
            token = res.get("nextPageToken")
            if not token:
                return drives

    def list_files(self, drive_id=None, query="trashed = false"):
        """Itera sobre todos los archivos visibles (todo 'Mi unidad' + 'Compartido conmigo'),
        o los de una unidad compartida si se da drive_id. Pagina hasta el final."""
        token = None
        while True:
            kwargs = dict(
                q=query,
                pageSize=1000,
                pageToken=token,
                fields=f"nextPageToken, incompleteSearch, files({FILE_FIELDS})",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                spaces="drive",
            )
            if drive_id:
                kwargs.update(corpora="drive", driveId=drive_id)
            else:
                kwargs.update(corpora="user")
            res = self._run(lambda: self._svc.files().list(**kwargs))
            yield from res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                return

    def list_children(self, folder_id: str):
        """Hijos directos de una carpeta (para exportar solo una carpeta concreta)."""
        return self.list_files(query=f"'{folder_id}' in parents and trashed = false")

    # ---------- descargas ----------
    def download(self, file_id: str, dest) -> None:
        """Descarga un archivo normal (PDF, foto...) en el objeto de archivo dest."""
        from googleapiclient.http import MediaIoBaseDownload

        def go():
            dest.seek(0)
            dest.truncate()
            req = self._svc.files().get_media(fileId=file_id, supportsAllDrives=True)
            dl = MediaIoBaseDownload(dest, req, chunksize=20 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk(num_retries=3)

        class _Req:  # with_retries espera algo con .execute()
            def execute(self_inner):
                return go()

        self._run(lambda: _Req())

    def export(self, file_id: str, mime: str, dest, export_link: str = None) -> None:
        """Exporta un archivo de Google (Docs, Hojas...) al formato mime.

        La exportación normal de la API falla con archivos de más de 10 MB
        (exportSizeLimitExceeded). En ese caso se prueba con el enlace de exportación
        directo, que admite archivos más grandes.
        """
        from googleapiclient.http import MediaIoBaseDownload

        def go():
            dest.seek(0)
            dest.truncate()
            req = self._svc.files().export_media(fileId=file_id, mimeType=mime)
            dl = MediaIoBaseDownload(dest, req, chunksize=20 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk(num_retries=3)

        class _Req:
            def execute(self_inner):
                return go()

        try:
            self._run(lambda: _Req())
        except DriveError as err:
            if err.reason != "exportSizeLimitExceeded" or not export_link:
                raise
            self._download_link(export_link, dest)

    def _download_link(self, url: str, dest) -> None:
        from google.auth.transport.requests import AuthorizedSession

        def go():
            dest.seek(0)
            dest.truncate()
            session = AuthorizedSession(self._creds)
            with session.get(url, stream=True, timeout=300) as r:
                if r.status_code != 200:
                    raise DriveError(f"El enlace de exportación devolvió {r.status_code}",
                                     "exportLinkFailed", r.status_code)
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    dest.write(chunk)

        for attempt in range(4):
            try:
                return go()
            except (ConnectionError, TimeoutError, OSError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    # ---------- escritura (solo con --mandar-a-papelera) ----------
    def trash(self, file_id: str) -> None:
        self._run(lambda: self._svc.files().update(
            fileId=file_id, body={"trashed": True}, supportsAllDrives=True))

