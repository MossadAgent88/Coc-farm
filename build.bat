@echo off
REM Build Coc-farm.exe with fixed output naming.
setlocal
cd /d "%~dp0"

echo Building Coc-farm.exe ...
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv\Scripts\python.exe" -m pip install pyinstaller
call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean CoCBot.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo DONE: %~dp0dist\Coc-farm\Coc-farm.exe
pause
