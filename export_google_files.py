import os
import io
import json
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# ============================================
# CONFIGURACIÓN
# ============================================
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
LOG_FILE = "export_log.txt"
PROGRESS_FILE = "progress.json"
OUTPUT_FOLDER = "exports"
ROOT_FOLDER_ID = "PEGA_AQUI_EL_ID_DE_TU_CARPETA"  # ver README: "¿Cómo obtener el ROOT_FOLDER_ID?"
ROOT_FOLDER_NAME = "Mi Drive"
SCOPES = ['https://www.googleapis.com/auth/drive']

# Si es True, tras exportar cada archivo se manda el original a la PAPELERA de Drive
# (recuperable durante 30 días). Desactivado por defecto por seguridad.
DELETE_ORIGINAL = False

# Reintentos en caso de error de red
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos

# ============================================
# HELPERS
# ============================================
def log(message):
    """Guarda y muestra mensaje"""
    print(message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def load_progress():
    """Carga progreso previo"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_progress(progress):
    """Guarda progreso"""
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(progress), f, indent=2)

def sanitize_filename(name):
    """Limpia caracteres inválidos en nombres de archivo"""
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Limitar longitud para evitar path too long en Windows
    if len(name) > 200:
        name = name[:200]
    return name.strip()

# ============================================
# AUTENTICACIÓN
# ============================================
def authenticate():
    """Autentica con Google Drive"""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('drive', 'v3', credentials=creds)

# ============================================
# FUNCIONES PRINCIPALES
# ============================================
def get_full_path(service, file_id, root_id, retries=0):
    """Obtiene ruta completa de un archivo con reintentos en caso de timeout"""
    try:
        metadata = service.files().get(
            fileId=file_id, 
            fields="id, name, parents"
        ).execute()
        
        name = sanitize_filename(metadata.get("name", "unnamed"))
        parents = metadata.get("parents", [])
        
        # Si llegamos a la raíz o no hay padre, retornar nombre
        if not parents or file_id == root_id:
            return name
        
        # Recursión para construir path completo
        parent_path = get_full_path(service, parents[0], root_id, retries)
        return os.path.join(parent_path, name)
    
    except Exception as e:
        # Reintentar en caso de timeout
        if retries < MAX_RETRIES:
            log(f"⚠️ Timeout obteniendo path, reintentando ({retries+1}/{MAX_RETRIES})...")
            time.sleep(RETRY_DELAY)
            return get_full_path(service, file_id, root_id, retries + 1)
        else:
            log(f"❌ Error obteniendo path después de {MAX_RETRIES} intentos: {str(e)}")
            return "error_path"

def export_file(service, file_metadata, base_path, progress):
    """Exporta solo archivos de Google (Docs/Sheets/Slides) y los elimina"""
    file_id = file_metadata["id"]
    file_name = sanitize_filename(file_metadata["name"])
    mime_type = file_metadata.get("mimeType", "")

    # Saltar si ya procesado
    if file_id in progress:
        log(f"⏩ Ya procesado: {file_name}")
        return

    # ============================================
    # CARPETAS → Procesar recursivamente
    # ============================================
    if mime_type == "application/vnd.google-apps.folder":
        folder_path = os.path.join(base_path, file_name)
        # NO crear carpeta todavía - solo preparar la ruta
        log(f"📂 Explorando carpeta: {file_name}")

        try:
            children = service.files().list(
                q=f"'{file_id}' in parents and trashed=false",
                fields="files(id, name, mimeType)"
            ).execute().get("files", [])

            # Procesar hijos - la carpeta se creará solo si hay archivos exportables
            for child in children:
                export_file(service, child, folder_path, progress)
        except Exception as e:
            log(f"❌ Error listando carpeta '{file_name}': {str(e)}")

        # Marcar carpeta como procesada
        progress.add(file_id)
        save_progress(progress)
        return

    # ============================================
    # SOLO EXPORTAR ARCHIVOS DE GOOGLE
    # ============================================
    GOOGLE_FORMATS = {
        "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
    }

    if mime_type not in GOOGLE_FORMATS:
        log(f"✗ Unsupported: {file_name} ({mime_type})")
        progress.add(file_id)
        save_progress(progress)
        return

    # ============================================
    # EXPORTAR ARCHIVO
    # ============================================
    export_mime, ext = GOOGLE_FORMATS[mime_type]
    local_path = os.path.join(base_path, file_name + ext)
    
    try:
        log(f"→ Exporting: {file_name}")
        
        # Intentar exportar con reintentos
        for attempt in range(MAX_RETRIES):
            try:
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                
                with io.FileIO(local_path, "wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                
                log(f"✓ Exported: {local_path}")
                break  # Éxito, salir del loop de reintentos
                
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    log(f"⚠️ Error en intento {attempt+1}, reintentando en {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    raise  # Último intento falló, propagar error

        # ============================================
        # MOVER ORIGINAL A LA PAPELERA DE DRIVE
        # ============================================
        # files().delete() lo borraría para siempre; con trashed=True se puede recuperar.
        if DELETE_ORIGINAL:
            try:
                service.files().update(fileId=file_id, body={"trashed": True}).execute()
                log(f"✓ Original movido a la papelera: {file_name}")
            except Exception as e:
                log(f"⚠️ No se pudo eliminar '{file_name}': {str(e)}")

        # Marcar como procesado
        progress.add(file_id)
        save_progress(progress)

    except HttpError as e:
        if e.resp.status == 403 and 'exportSizeLimitExceeded' in str(e):
            log(f"❌ Archivo demasiado grande para exportar: {file_name}")
        else:
            log(f"❌ Error HTTP exportando '{file_name}': {str(e)}")
        progress.add(file_id)
        save_progress(progress)
    except Exception as e:
        log(f"❌ Error exportando '{file_name}': {str(e)}")

# ============================================
# MAIN
# ============================================
def main():
    log("="*60)
    log("🚀 Iniciando exportación de Google Drive")
    log("="*60)
    
    # Autenticar
    log("🔐 Autenticando...")
    service = authenticate()
    log("✅ Autenticación exitosa")
    
    # Configurar salida
    output_path = os.path.join(OUTPUT_FOLDER, ROOT_FOLDER_NAME)
    os.makedirs(output_path, exist_ok=True)
    
    # Cargar progreso
    progress = load_progress()
    log(f"📊 Archivos ya procesados: {len(progress)}")
    
    # Buscar archivos
    log(f"🔍 Buscando archivos en carpeta raíz...")
    try:
        results = service.files().list(
            q=f"'{ROOT_FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name, mimeType)",
            pageSize=1000
        ).execute()
        
        all_files = results.get("files", [])
        log(f"📦 Archivos encontrados: {len(all_files)}")
        
        # Procesar cada archivo
        for idx, file_item in enumerate(all_files, 1):
            log(f"\n[{idx}/{len(all_files)}] Procesando...")
            export_file(service, file_item, output_path, progress)
    
    except Exception as e:
        log(f"❌ Error en búsqueda principal: {str(e)}")
    
    log("="*60)
    log("🎉 Exportación completada")
    log(f"📁 Archivos en: {os.path.abspath(output_path)}")
    log(f"📊 Total procesados: {len(progress)}")
    log("="*60)

if __name__ == "__main__":
    main()