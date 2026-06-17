@echo off
setlocal
cd /d "%~dp0"
if exist "dist\Coc-farm\Coc-farm.exe" (
    start "" "dist\Coc-farm\Coc-farm.exe"
    exit /b 0
)
if exist "Coc-farm\Coc-farm.exe" (
    start "" "Coc-farm\Coc-farm.exe"
    exit /b 0
)
echo [ERROR] Coc-farm.exe not found. Build first or extract Coc-farm.zip.
pause
exit /b 1
