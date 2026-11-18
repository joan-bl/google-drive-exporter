# 📦 Google Drive Exporter

Copia **todo tu Google Drive al ordenador**, ordenado y con sus fechas, sin el lío de los zips de Google Takeout.

- **Todo**: *Mi unidad*, *Compartido conmigo* y las *unidades compartidas*, cada una en su carpeta.
- **Docs, Hojas y Presentaciones convertidos** a Word, Excel y PowerPoint (o PDF, ODT, Markdown…, incluso varios a la vez).
- **Fechas originales**: cada archivo conserva la fecha de modificación de Drive (y en Windows también la de creación). Así puedes ordenar por fecha en el Explorador.
- **Accesos directos resueltos**: si en Mi unidad tienes un acceso a una carpeta compartida, se baja la carpeta de verdad en ese sitio, una sola vez.
- **Sin choques de nombres**: dos archivos que se llaman igual no se machacan (`foto.jpg` y `foto (2).jpg`).
- **Reanudable e incremental**: si se corta, sigue donde estaba. Si lo vuelves a ejecutar meses después, solo baja lo nuevo o lo cambiado, y si renombraste algo en Drive lo renombra también en tu disco.
- **Comprobado**: verifica la suma MD5 de cada archivo descargado.
- **Índice con todo**: un `_informe.html` que se puede buscar y ordenar por fecha, y un `_indice.csv` para Excel. Incluye lo que no se pudo bajar y por qué (formularios, archivos con la descarga desactivada…).
- **Solo lectura**: pide a Google permiso **solo para leer**. No toca nada de tu Drive (salvo que actives a propósito `--mandar-a-papelera`).

## ¿Por qué no Google Takeout?

Takeout te da varios zips de 2 GB, **no incluye lo de "Compartido conmigo"** que no esté en tu unidad y pierde las fechas de los archivos. Este programa baja directamente a una carpeta normal, igual que la ves en Drive.

## Cómo queda

```
exports/
├── Mi unidad/
│   ├── Universidad/
│   │   ├── Informe final.docx
│   │   ├── Presupuesto.xlsx
│   │   └── foto.jpg
│   └── Carpeta compartida (acceso directo)/
├── Mi unidad (sin carpeta)/        ← archivos tuyos que se quedaron sin carpeta
├── Compartido conmigo/
├── Unidades compartidas/
│   └── Equipo/
├── _informe.html                   ← índice para buscar y ordenar
├── _indice.csv
└── .drive-exporter/                ← estado para reanudar y registro
```

Con `--orden fecha` se organiza por fecha de modificación: `Mi unidad/2024/2024-03/…`.

## Instalación

Necesitas Python 3.9 o superior.

```bash
pip install -r requirements.txt
```

### Credenciales de Google (una sola vez)

Google exige que cada programa que usa tu Drive tenga unas credenciales propias. Son gratis:

1. Entra en [Google Cloud Console](https://console.cloud.google.com/) y crea un proyecto.
2. Activa la **Google Drive API** (menú *APIs y servicios → Biblioteca*).
3. Ve a **Google Auth Platform** (antes "Pantalla de consentimiento de OAuth"), elige **Externo** y rellena los campos obligatorios.
4. En **Público** (*Audience*) → **Usuarios de prueba**, **añade tu propio correo de Gmail**. Si no lo haces, al dar permiso verás *"Acceso bloqueado: … no ha completado el proceso de verificación de Google"*.
5. En **Clientes** (*Credentials*) → **Crear cliente** → tipo **Aplicación de escritorio**. Descarga el JSON.
6. Renómbralo a `credentials.json` y ponlo en la carpeta del programa.

La primera vez que ejecutes el programa se abrirá el navegador para que des permiso. El permiso se guarda en `token_lectura.json`, así que no te lo volverá a pedir.

> En modo "prueba", Google caduca el permiso cada 7 días. Si pasa, el programa vuelve a abrir el navegador; no hay que hacer nada más.

## Uso

**Fácil (Windows):** doble clic en `exportar.bat`. Un asistente te pregunta qué exportar y dónde.

**Desde la terminal:**

```bash
python -m drive_exporter                         # asistente con preguntas
python -m drive_exporter --si                    # todo, a la carpeta exports/
python -m drive_exporter --simular               # ver qué haría, sin descargar nada
python -m drive_exporter -o "D:\Copia Drive"     # en otra carpeta
python -m drive_exporter --origen compartido     # solo "Compartido conmigo"
python -m drive_exporter --carpeta https://drive.google.com/drive/folders/1AbC...
python -m drive_exporter --doc docx,pdf --sheet xlsx,pdf   # cada documento en dos formatos
python -m drive_exporter --orden fecha           # carpetas por año y mes
python -m drive_exporter --solo-google           # solo Docs/Hojas/Presentaciones (como la v1)
```

| Opción | Qué hace |
|---|---|
| `-o`, `--salida` | Carpeta de destino (por defecto `exports`) |
| `--origen` | `mi-unidad`, `compartido` o `unidades`. Se puede repetir. Por defecto, todo |
| `--carpeta` | Solo una carpeta (ID o enlace) |
| `--doc`, `--sheet`, `--slides`, `--drawing` | Formatos de exportación, separados por comas |
| `--solo-google` | No bajar PDFs, fotos, etc.; solo convertir los archivos de Google |
| `--orden` | `carpetas` (como en Drive) o `fecha` (`AAAA/AAAA-MM`) |
| `--accesos-directos` | `seguir` (por defecto) o `ignorar` |
| `--hilos` | Descargas en paralelo (por defecto 4) |
| `--simular` | No descarga; genera el índice con lo que haría |
| `--sin-navegador` | Muestra el enlace de permiso en vez de abrir el navegador |
| `--mandar-a-papelera` | ⚠️ Tras exportarlos, manda a la papelera de Drive tus Docs/Hojas/Presentaciones. Pide confirmación y permiso de escritura |
| `-s`, `--si` | No preguntar antes de empezar |

### Formatos disponibles

| Tipo de Google | Por defecto | Otros |
|---|---|---|
| Documentos | `docx` | `pdf`, `odt`, `rtf`, `txt`, `md`, `epub`, `html.zip` |
| Hojas de cálculo | `xlsx` | `pdf`, `ods`, `csv`*, `tsv`*, `html.zip` |
| Presentaciones | `pptx` | `pdf`, `odp`, `txt`, `png`*, `jpg`*, `svg`* |
| Dibujos | `png` | `jpg`, `svg`, `pdf` |
| Apps Script | `json` | |

\* Solo la primera hoja o diapositiva (limitación de Google).

## Lo que no se puede bajar

Queda anotado en el índice con su enlace, para que lo revises a mano:

- **Formularios de Google**: la API no los exporta. Las respuestas suelen estar en una Hoja vinculada, que sí se baja.
- **Google Sites y My Maps**.
- **Archivos con la descarga desactivada** por su propietario.
- **Documentos enormes**: si un Doc pasa del límite de exportación de la API (10 MB), el programa lo intenta por otra vía que admite archivos más grandes. Si aun así falla, aparece como error.

## Preguntas frecuentes

**¿Se ha cortado a medias?** Vuelve a ejecutar lo mismo. Lo ya bajado aparece como *sin cambios* y sigue con el resto.

**¿Quiero tener la copia al día?** Ejecuta lo mismo cada cierto tiempo. Solo se baja lo nuevo o lo modificado. Lo que borres en Drive **no** se borra de tu copia.

**¿Lo compartido conmigo que también tengo en Mi unidad se baja dos veces?** No. Se baja una vez (en Mi unidad) y en *Compartido conmigo* queda anotado como repetido, con la ruta donde está.

**¿Qué hago con el `progress.json` de la versión 1?** Nada, ya no se usa. La v2 guarda su estado en `exports/.drive-exporter/estado.sqlite`.

## Desarrollo

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas usan un Drive falso en memoria (`tests/fake_drive.py`) que imita a la API: carpetas, archivos con el mismo nombre, accesos directos (incluido uno roto), compartidos, unidades compartidas, archivos huérfanos, exportaciones que superan el límite y descargas corruptas.

```
drive_exporter/
├── cli.py         línea de comandos y asistente
├── api.py         todo lo que habla con Google (permisos, listados, descargas, reintentos)
├── planner.py     reconstruye el árbol y decide qué va dónde y con qué nombre
├── exporter.py    descarga en paralelo, verifica MD5, pone fechas y reanuda
├── state.py       estado en SQLite para reanudar y actualizar
├── report.py      índice CSV e informe HTML
├── names.py       nombres válidos en Windows y sin choques
├── timestamps.py  fechas de modificación y creación
└── formats.py     tipos de Google y formatos de exportación
```

## Historial

- **v2.0 (noviembre 2026)**: reescrito entero. Exporta Mi unidad, Compartido conmigo y unidades compartidas; baja también los archivos normales; conserva las fechas; sigue accesos directos; actualización incremental; verificación MD5; índice HTML/CSV; permiso de solo lectura; descargas en paralelo; asistente y `exportar.bat`. Arregla que la v1 solo veía los 100 primeros elementos de cada carpeta.
- **v1 (diciembre 2024)**: script que exportaba los Docs, Hojas y Presentaciones de una carpeta.

## Licencia

MIT. Autor: [joan-bl](https://github.com/joan-bl)
