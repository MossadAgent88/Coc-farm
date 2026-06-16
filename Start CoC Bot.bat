@echo off
REM ============================================================
REM  Start CoC Bot
REM  Double-click to launch the bot. The FIRST run installs
REM  everything automatically (one time, ~1-2 min). After that
REM  it just opens the app window with no console.
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- First run: set up the virtual environment -------------
if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  First-time setup -- installing the bot. This happens once.
    echo.

    where python >nul 2>nul
    if errorlevel 1 (
        echo  [ERROR] Python is not installed or not on PATH.
        echo          Install Python 3.11+ from https://www.python.org/downloads/
        echo          and tick "Add Python to PATH" during install, then run this again.
        echo.
        pause
        exit /b 1
    )

    python -m venv .venv
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
