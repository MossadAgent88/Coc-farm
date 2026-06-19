param(
    [switch]$Build,
    [string]$Version = "1.5.5",
    [string]$OutputDir = "release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($Build) {
    $BuildVenv = ".venv-build"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

    if (Test-Path $BuildPython) {
        & $BuildPython -c "import struct, sys; raise SystemExit(0 if sys.version_info[:2] == (3, 14) and struct.calcsize('P') * 8 == 64 else 1)" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $BuildVenv -Recurse -Force
        }
    }

    if (!(Test-Path $BuildPython)) {
        $Candidates = @()
        if ($env:PYTHON_BUILD) {
            $Candidates += ,@($env:PYTHON_BUILD)
        }
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $Candidates += ,@("py", "-3.14")
        }
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            uv python install 3.14
            $UvPython = (uv python find 3.14).Trim()
            if ($UvPython) {
                $Candidates += ,@($UvPython)
            }
        }
        $Candidates += ,@("python")

        $SelectedPython = $null
        foreach ($Candidate in $Candidates) {
            $Command = $Candidate[0]
            $Args = @()
            if ($Candidate.Count -gt 1) {
                $Args = $Candidate[1..($Candidate.Count - 1)]
            }
            try {
                & $Command @Args -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 14), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture()" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    $SelectedPython = $Candidate
                    break
                }
            } catch {
                continue
            }
        }
        if ($null -eq $SelectedPython) {
            throw "Python 3.14 x64 is required to build the Windows release."
        }
        $SelectedCommand = $SelectedPython[0]
        $SelectedArgs = @()
        if ($SelectedPython.Count -gt 1) {
            $SelectedArgs = $SelectedPython[1..($SelectedPython.Count - 1)]
        }
        & $SelectedCommand @SelectedArgs -m venv $BuildVenv
    }
    & $BuildPython -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 14), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture(); print(sys.version)"
    & $BuildPython -m pip install --upgrade pip setuptools wheel
    & $BuildPython -m pip install -r requirements.txt
    & $BuildPython -m pip install -r requirements-build.txt
    & $BuildPython -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 QtWebEngine import OK')"
    & $BuildPython -m PyInstaller --noconfirm --clean CoCBot.spec
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
$ReleaseNotesName = "RELEASE_NOTES_v$Version.md"
$ReleaseNotesPath = Join-Path $RepoRoot "release_assets\$ReleaseNotesName"
if (!(Test-Path $ReleaseNotesPath)) {
    $ReleaseNotesName = "RELEASE_NOTES_v1.0.0.md"
    $ReleaseNotesPath = Join-Path $RepoRoot "release_assets\$ReleaseNotesName"
}
Copy-Item -LiteralPath $ReleaseNotesPath -Destination (Join-Path $Stage $ReleaseNotesName) -Force

if (Test-Path $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -Force

$Hash = Get-FileHash -Path $ZipPath -Algorithm SHA256
"$($Hash.Hash)  CoC-Farm-Bot-Windows.zip" | Set-Content -Path $ChecksumPath -Encoding ASCII

Write-Host "Created $ZipPath"
Write-Host "Created $ChecksumPath"
