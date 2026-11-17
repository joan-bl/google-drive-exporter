# 📦 Google Drive Folder Exporter

Script en Python para **exportar archivos de Google Drive** (Docs, Sheets, Slides) a formatos estándar (.docx, .xlsx, .pptx) y, opcionalmente, **mandar los originales a la papelera** de Drive.

---

## 🎯 ¿Qué hace este proyecto?

Este script resuelve un problema específico: **los archivos de Google Workspace no se pueden descargar directamente** con la aplicación de escritorio de Drive (se descargan como accesos directos de 1KB).

### Funcionalidades principales:

✅ **Exporta solo archivos de Google**:
- Google Docs → `.docx`
- Google Sheets → `.xlsx`
- Google Slides → `.pptx`

✅ **Ignora archivos normales** (PDFs, imágenes, ZIPs, etc.)

✅ **Opcional:** manda los originales a la papelera de Drive después de exportar (`DELETE_ORIGINAL = True`). Se pueden recuperar durante 30 días

✅ **Sistema de reanudación**: Si se interrumpe, continúa donde se quedó

✅ **Solo crea carpetas con contenido**: Evita carpetas vacías

✅ **Reintentos automáticos**: Maneja timeouts y errores de red

---

## 📁 Estructura del proyecto

```
drive-exporter/
│
├── export_google_files.py    # Script principal
├── credentials.json           # Credenciales OAuth de Google Cloud
├── token.json                 # Token generado tras autenticar (auto-creado)
│
├── progress.json              # Registro de archivos procesados (auto-creado)
├── export_log.txt             # Log detallado de operaciones (auto-creado)
│
└── exports/                   # Carpeta de salida (auto-creada)
    └── Mi Drive/
        ├── Subcarpeta1/
        ├── Subcarpeta2/
        └── ...
```

---

## 🔧 Requisitos previos

### 1. Python 3.7+
Verifica tu versión:
```bash
python --version
```

### 2. Dependencias
Instala las librerías necesarias:
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

O con conda:
```bash
conda install -c conda-forge google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

### 3. Credenciales de Google Cloud

#### Paso 1: Crear proyecto en Google Cloud
1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto
3. Habilita la **Google Drive API**

#### Paso 2: Configurar OAuth
1. Ve a **APIs & Services → OAuth consent screen**
2. Selecciona **External** y completa los campos obligatorios
3. Ve a **Credentials → Create Credentials → OAuth Client ID**
4. Selecciona **Desktop app**
5. Descarga el archivo JSON

#### Paso 3: Colocar credenciales
1. Renombra el archivo descargado a `credentials.json`
2. Colócalo en la carpeta del proyecto

---

## 🚀 Configuración

Abre `export_google_files.py` y configura estas variables:

```python
# ID de la carpeta de Drive a exportar
ROOT_FOLDER_ID = "PEGA_AQUI_EL_ID_DE_TU_CARPETA"

# Nombre de la carpeta (para crear subcarpeta local)
ROOT_FOLDER_NAME = "Mi Drive"

# Mandar los originales a la papelera tras exportar (desactivado por defecto)
DELETE_ORIGINAL = False

# Carpeta de salida
OUTPUT_FOLDER = "exports"
```

### ¿Cómo obtener el ROOT_FOLDER_ID?

1. Abre la carpeta en Google Drive (navegador web)
2. Copia el ID de la URL:
   ```
   https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345
                                          └─────────────────┬──────────────────┘
                                                       Copia este ID
   ```

---

## ▶️ Uso

### 1. Primera ejecución

```bash
cd "C:\Users\tu_usuario\ruta\drive-exporter"
python export_google_files.py
```

- Se abrirá tu navegador para autorizar el acceso
- Acepta los permisos
- El script comenzará a exportar

### 2. Ejecuciones posteriores

El script usará el token guardado (`token.json`), no pedirá autorización de nuevo.

### 3. Continuar una exportación interrumpida

Si el script se interrumpe (corte de internet, apagar PC, etc.):

```bash
python export_google_files.py
```

Continuará **automáticamente desde donde se quedó** gracias a `progress.json`.

---

## 📊 Ejemplo de salida

```
============================================================
🚀 Iniciando exportación de Google Drive
============================================================
🔐 Autenticando...
✅ Autenticación exitosa
📊 Archivos ya procesados: 1247
🔍 Buscando archivos en carpeta raíz...
📦 Archivos encontrados: 2502

[1/2502] Procesando...
📂 Explorando carpeta: Universidad
→ Exporting: codigo
✓ Exported: exports\Mi Drive\Universidad\...\codigo.docx
✓ Original movido a la papelera: codigo

[2/2502] Procesando...
✗ Unsupported: foto.jpg (image/jpeg)

[3/2502] Procesando...
→ Exporting: Informe final
✓ Exported: exports\Mi Drive\...\Informe final.docx
✓ Original movido a la papelera: Informe final

...

============================================================
🎉 Exportación completada
📁 Archivos en: C:\Users\...\drive-exporter\exports\Mi Drive
📊 Total procesados: 2502
============================================================
```

---

## 🔄 Sistema de reanudación

El archivo `progress.json` guarda el ID de cada archivo procesado:

```json
[
  "1H_mTd1vCoN2IAOkdOj2fzMk8FHYHodjUi9S5B9GZnk8",
  "1X9FOchlS2j_6R7ice4V757Cc9BlKVMZjpsdWGy0rr7k",
  ...
]
```

### Beneficios:

✅ **Nunca procesa dos veces el mismo archivo**  
✅ **Continúa tras interrupciones** (apagar PC, cortes de internet)  
✅ **Permite pausar y reanudar días después**  
✅ **Re-ejecutar no repite trabajo**

---

## ⚙️ Configuración avanzada

### Ajustar reintentos

Si experimentas muchos timeouts, aumenta:

```python
MAX_RETRIES = 5      # Intentos por archivo (default: 3)
RETRY_DELAY = 10     # Segundos entre reintentos (default: 5)
```

### Cambiar carpeta de salida

```python
OUTPUT_FOLDER = "mis_exportaciones"
```

### Mandar los originales a la papelera

```python
DELETE_ORIGINAL = True
```

⚠️ Los originales van a la **papelera** de Drive (no se borran para siempre). Desde allí se recuperan durante 30 días.

---

## 🛑 Limitaciones conocidas

1. **Archivos muy grandes** (>50MB en Google Docs):
   - Google Drive tiene límite de exportación
   - Se registra en el log como `exportSizeLimitExceeded`

2. **Solo archivos de Google Workspace**:
   - No descarga PDFs, imágenes, ZIPs, etc.
   - Esto es **intencional** para evitar duplicados

3. **Límite de API**:
   - Google limita a ~1000 peticiones/100 segundos
   - El script maneja esto con reintentos

---

## 📝 Archivos generados

### `progress.json`
Registro de IDs procesados. **No borrar** si quieres continuar una exportación.

### `export_log.txt`
Log completo de operaciones:
```
→ Exporting: documento.docx
✓ Exported: exports\...\documento.docx
✓ Original movido a la papelera: documento
✗ Unsupported: imagen.png (image/png)
❌ Error exportando 'archivo_grande': exportSizeLimitExceeded
```

### `token.json`
Token de autenticación. Se regenera automáticamente si caduca.

---

## 🐛 Solución de problemas

### Error: `credentials.json not found`
**Solución**: Descarga el archivo desde Google Cloud Console y colócalo en la carpeta del proyecto.

### Error: `TimeoutError: The read operation timed out`
**Solución**: El script reintenta automáticamente. Si persiste, aumenta `MAX_RETRIES` y `RETRY_DELAY`.

### Error: `exportSizeLimitExceeded`
**Solución**: El archivo es demasiado grande para exportar. Edítalo manualmente en Drive para reducir su tamaño.

### Carpetas vacías creadas
**Solución**: ✅ Ya solucionado en esta versión. Las carpetas solo se crean si contienen archivos exportables.

### El script se detiene inesperadamente
**Solución**: Ejecuta de nuevo. Continuará desde donde se quedó gracias a `progress.json`.

---

## 🔒 Seguridad

- **Las credenciales son privadas**: No compartas `credentials.json` ni `token.json`
- **Permisos OAuth**: Solo requiere acceso a Google Drive
- **Datos locales**: Todo se guarda en tu PC, no se envía a terceros

---

## 📞 Soporte

Si encuentras problemas:

1. Revisa `export_log.txt` para ver errores específicos
2. Verifica que `credentials.json` esté configurado correctamente
3. Asegúrate de tener conexión a internet estable
4. Comprueba que la carpeta de Drive exista y tengas permisos

---

## 📜 Licencia

Este proyecto es de código abierto. Úsalo libremente.

---

## 🎉 Estado del proyecto

**✅ FUNCIONANDO** - Script probado y operativo

**Última actualización**: Diciembre 2024

---

## 🙏 Créditos

Script creado para resolver el problema de exportación masiva de archivos de Google Workspace.

**Autor**: [joan-bl](https://github.com/joan-bl)
