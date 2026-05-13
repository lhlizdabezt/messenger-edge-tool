@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" goto setup
"%VENV_PY%" -c "import sys" >nul 2>nul
if errorlevel 1 goto setup
goto run

:setup
echo Chua thay moi truong Python hoac moi truong cu bi hong. Dang chay setup truoc...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo Setup that bai.
  pause
  exit /b 1
)

:run
"%VENV_PY%" "%~dp0messenger_tool.py"
pause
