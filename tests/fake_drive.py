"""Un Google Drive de mentira, en memoria, con la misma interfaz que api.DriveClient."""

import hashlib

from drive_exporter.api import DriveError

DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
FORM = "application/vnd.google-apps.form"


class FakeDrive:
    def __init__(self):
        self.files = {}
        self.content = {}
        self.drives = []
        self.calls = []
        self.trashed = []
        self.export_limit = set()   # ids que fallan con exportSizeLimitExceeded
        self.corrupt = set()        # ids que se descargan con contenido distinto al md5

    # ----- montar el escenario -----
    def add(self, fid, name, mime="application/octet-stream", parents=("root",), content=None,
            created="2021-01-01T10:00:00.000Z", modified="2022-02-02T12:00:00.000Z", **extra):
        item = {"id": fid, "name": name, "mimeType": mime, "parents": list(parents),
                "createdTime": created, "modifiedTime": modified, "ownedByMe": True,
                "owners": [{"displayName": "Yo", "emailAddress": "yo@example.com"}],
                "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
                "capabilities": {"canDownload": True}}
        if not parents:
            del item["parents"]
        if content is not None and not mime.startswith("application/vnd.google-apps."):
            item["size"] = str(len(content))
            item["md5Checksum"] = hashlib.md5(content).hexdigest()
        if content is not None:
            self.content[fid] = content
        item.update(extra)
        self.files[fid] = item
        return item

    def touch(self, fid, modified, content=None):
        self.files[fid]["modifiedTime"] = modified
        if content is not None:
            self.content[fid] = content
            if "md5Checksum" in self.files[fid]:
                self.files[fid]["md5Checksum"] = hashlib.md5(content).hexdigest()
                self.files[fid]["size"] = str(len(content))

    # ----- interfaz de DriveClient -----
    def about(self):
        return {"user": {"displayName": "Yo", "emailAddress": "yo@example.com"}}

    def root_id(self):
        return "root"

    def list_shared_drives(self):
        return list(self.drives)

    def list_files(self, drive_id=None, query="trashed = false"):
        self.calls.append(("list", drive_id, query))
        for f in self.files.values():
            in_drive = f.get("driveId")
            if drive_id:
                if in_drive == drive_id:
                    yield dict(f)
            elif "' in parents" in query:
                parent = query.split("'")[1]
                if parent in (f.get("parents") or []):
                    yield dict(f)
            elif not in_drive and not f.get("_hidden"):
                yield dict(f)

    def list_children(self, folder_id):
        return self.list_files(query=f"'{folder_id}' in parents and trashed = false")

    def get_file(self, fid):
        f = self.files.get(fid)
        return dict(f) if f and not f.get("_noaccess") else None

    def download(self, fid, fh):
        self.calls.append(("download", fid))
        data = self.content[fid]
        if fid in self.corrupt:
            data = data + b"X"
        fh.write(data)

    def export(self, fid, mime, fh, export_link=None):
        self.calls.append(("export", fid, mime))
        if fid in self.export_limit:
            if not export_link:
                raise DriveError("too big", "exportSizeLimitExceeded", 403)
            self.calls.append(("export_link", fid))
        fh.write(f"EXPORT {fid} {mime} {self.files[fid]['modifiedTime']}".encode())

    def trash(self, fid):
        self.trashed.append(fid)
        self.files[fid]["trashed"] = True


def scenario():
    d = FakeDrive()
    d.add("A", "Universidad", FOLDER, created="2019-09-01T08:00:00.000Z", modified="2023-06-30T10:00:00.000Z")
    d.add("doc1", "Informe", DOC, parents=["A"], content=b"",
          exportLinks={"application/pdf": "https://x/pdf",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "https://x/docx"})
    d.add("bin1", "Informe.docx", parents=["A"], content=b"docx real")
    d.add("img1", "foto.jpg", "image/jpeg", parents=["A"], content=b"jpeg1",
          created="2020-01-01T00:00:00.000Z", modified="2020-05-05T05:05:05.000Z")
    d.add("img2", "FOTO.jpg", "image/jpeg", parents=["A"], content=b"jpeg2",
          created="2021-01-01T00:00:00.000Z")
    d.add("B", "Tema: 1/2?", FOLDER, parents=["A"])
    d.add("sh1", "Notas", SHEET, parents=["B"], content=b"")
    d.add("form1", "Encuesta", FORM, parents=["A"])
    d.add("nodl", "Protegido.pdf", "application/pdf", parents=["A"], content=b"p",
          capabilities={"canDownload": False})
    # Compartido conmigo: carpeta S (su padre no es visible) y archivo T suelto
    d.add("S", "Carpeta de Ana", FOLDER, parents=["padre-de-ana"], ownedByMe=False,
          sharedWithMeTime="2023-01-01T00:00:00.000Z")
    d.add("s1", "apuntes.pdf", "application/pdf", parents=["S"], content=b"pdf de ana", ownedByMe=False)
    d.add("T", "suelto.txt", "text/plain", parents=[], content=b"hola", ownedByMe=False,
          sharedWithMeTime="2023-01-01T00:00:00.000Z")
    # Acceso directo en Mi unidad que apunta a la carpeta compartida S
    d.add("cut1", "Atajo a Ana", SHORTCUT, shortcutDetails={"targetId": "S", "targetMimeType": FOLDER})
    d.add("cut2", "Roto", SHORTCUT, shortcutDetails={"targetId": "no-existe", "targetMimeType": DOC})
    # Archivo mío sin carpeta (huérfano)
    d.add("O", "perdido.txt", "text/plain", parents=["carpeta-borrada"], content=b"orphan")
    # Unidad compartida
    d.drives.append({"id": "D1", "name": "Equipo"})
    d.add("d1", "plan.txt", "text/plain", parents=["D1"], content=b"plan", driveId="D1")
    return d
