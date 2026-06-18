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
if not exist ".venv-build\Scripts\python.exe" python -m venv .venv-build
call ".venv-build\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul
call ".venv-build\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
call ".venv-build\Scripts\python.exe" -c "import webview; import clr; print('webview/pythonnet import OK')"
call ".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean CoCBot.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo DONE: %~dp0dist\Coc-farm\Coc-farm.exe
pause
