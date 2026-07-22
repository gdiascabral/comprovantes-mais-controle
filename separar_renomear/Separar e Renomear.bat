@echo off
chcp 65001 >nul
cd /d "%~dp0"
python separar_renomear.py
if errorlevel 1 (
  echo.
  echo Se deu erro acima, rode primeiro o "instalar.bat" na pasta principal.
  pause
)
