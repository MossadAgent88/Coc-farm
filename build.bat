@echo off
setlocal
cd /d "%~dp0"

echo Building CoC Farm Bot Windows release ZIP ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_release.ps1"
if errorlevel 1 (
    echo [ERROR] Release build failed.
    pause
    exit /b 1
)

echo DONE: %~dp0dist\CoC-Farm-Bot-Windows.zip
pause
