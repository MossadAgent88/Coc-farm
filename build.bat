@echo off
REM ============================================================
REM  Build CoCBot.exe  (run this ONCE to create a standalone app)
REM  Double-click this file. When it finishes you'll have:
REM       dist\CoCBot.exe   <-- your app, no Python folder needed
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo  Building CoCBot.exe ...
echo.

REM --- Make sure Python exists -------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] Python is not installed or not on PATH.
    echo          Install Python 3.11+ from https://www.python.org/downloads/
    echo          and tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM --- Create the virtual environment on first run -----------
if not exist ".venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv .venv
)

REM --- Install dependencies + PyInstaller --------------------
echo  Installing dependencies ^(this can take a minute^)...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
call ".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 (
    echo  [ERROR] Dependency install failed. See messages above.
    pause
    exit /b 1
)

REM --- Build ------------------------------------------------
echo.
echo  Packaging the app...
call ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean CoCBot.spec
if errorlevel 1 (
    echo  [ERROR] Build failed. See messages above.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   DONE!  Your app is here:
echo        %~dp0dist\CoCBot.exe
echo.
echo   You can move CoCBot.exe anywhere, double-click it to run,
echo   or right-click it to pin to Start / Taskbar.
echo  ============================================================
echo.
pause
