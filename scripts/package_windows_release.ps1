param(
    [switch]$Build,
    [string]$Version = "1.0.0",
    [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($Build) {
    if (!(Test-Path ".venv\Scripts\python.exe")) {
        python -m venv .venv
    }
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m pip install pyinstaller
    .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean CoCBot.spec
}

$BuiltDir = Join-Path $RepoRoot "dist\Coc-farm"
$BuiltExe = Join-Path $BuiltDir "Coc-farm.exe"
if (!(Test-Path $BuiltExe)) {
    throw "Missing build output: $BuiltExe. Run with -Build or run build.bat first."
}

$OutRoot = Join-Path $RepoRoot $OutputDir
$Stage = Join-Path $OutRoot "CoC-Farm-Bot-Windows"
$ZipPath = Join-Path $OutRoot "CoC-Farm-Bot-Windows.zip"
$ChecksumPath = "$ZipPath.sha256"

if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Copy-Item -LiteralPath (Join-Path $BuiltDir "_internal") -Destination (Join-Path $Stage "_internal") -Recurse -Force
Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $Stage "CoC Farm Bot.exe") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "release_assets\QUICK_START.txt") -Destination (Join-Path $Stage "QUICK_START.txt") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "release_assets\settings.example.json") -Destination (Join-Path $Stage "settings.example.json") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "release_assets\CHANGELOG.txt") -Destination (Join-Path $Stage "CHANGELOG.txt") -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "release_assets\RELEASE_NOTES_v1.0.0.md") -Destination (Join-Path $Stage "RELEASE_NOTES_v1.0.0.md") -Force

if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force

$Hash = Get-FileHash -Path $ZipPath -Algorithm SHA256
"$($Hash.Hash)  CoC-Farm-Bot-Windows.zip" | Set-Content -Path $ChecksumPath -Encoding ASCII

Write-Host "Created $ZipPath"
Write-Host "Created $ChecksumPath"
