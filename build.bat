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
if not exist ".venv-build\Scripts\python.exe" py -3.12 -m venv .venv-build
call ".venv-build\Scripts\python.exe" -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 12), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture(); print(sys.version)"
if errorlevel 1 (
    echo [ERROR] Build requires Python 3.12 x64.
    pause
    exit /b 1
)
call ".venv-build\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >nul
call ".venv-build\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv-build\Scripts\python.exe" -m pip install -r requirements-build.txt
call ".venv-build\Scripts\python.exe" -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 QtWebEngine import OK')"
call ".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean CoCBot.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo DONE: %~dp0dist\Coc-farm\Coc-farm.exe
pause
