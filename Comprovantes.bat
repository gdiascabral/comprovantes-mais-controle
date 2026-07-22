@echo off
chcp 65001 >nul
cd /d "%~dp0"
python comprovantes_app.py
if errorlevel 1 (
  echo.
  echo Se deu erro acima, rode primeiro o "instalar.bat" nesta pasta.
  pause
)
