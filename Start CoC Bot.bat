@echo off
REM ============================================================
REM  Start CoC Bot
REM  Double-click to launch the bot. The FIRST run installs
REM  everything automatically (one time, ~1-2 min). After that
REM  it just opens the app window with no console.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- First run: set up the virtual environment -------------
if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  First-time setup -- installing the bot. This happens once.
    echo.

    set "PYTHON_CMD="
    py -3.14 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.14"
    if not defined PYTHON_CMD (
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
    if not defined PYTHON_CMD (
        echo  [ERROR] Python 3.14 x64 is required for source runs.
        echo          Python 3.15 is not supported yet.
        echo.
        pause
        exit /b 1
    )

    !PYTHON_CMD! -m venv .venv
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] Install failed. See messages above.
        pause
        exit /b 1
    )
    echo.
    echo  Setup complete. Launching...
)

REM --- Launch the GUI with no console window -----------------
start "" ".venv\Scripts\pythonw.exe" gui.py
exit /b 0
