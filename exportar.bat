@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q --disable-pip-version-check -r requirements.txt
python -m drive_exporter %*
echo.
echo Ha terminado. Pulsa cualquier tecla para cerrar esta ventana.
pause >nul
