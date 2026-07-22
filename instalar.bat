@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando dependencias...
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [ERRO] Falha no pip. Verifique se o Python esta instalado e no PATH.
  pause
  exit /b 1
)
echo Instalando o Chrome do Playwright...
python -m playwright install chrome
echo.
echo Instalacao concluida!
pause
