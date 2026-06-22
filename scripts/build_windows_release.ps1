param(
    [switch]$Build,
    [switch]$NoBuild,
    [string]$Version = "",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Get-ReleaseVersion {
    param([string]$RequestedVersion)

    if (![string]::IsNullOrWhiteSpace($RequestedVersion)) {
        return $RequestedVersion.Trim().TrimStart("v")
    }

    $tag = ""
    try {
        $tag = (& git describe --tags --exact-match 2>$null).Trim()
    } catch {
        $tag = ""
    }
    if ($tag) {
        return $tag.TrimStart("v")
    }

    $initPath = Join-Path $RepoRoot "cocbot\__init__.py"
    $initText = Get-Content -LiteralPath $initPath -Raw
    if ($initText -match '__version__\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }

    return "0.0.0"
}

function Test-Python314 {
    param([string[]]$Candidate)

    $command = $Candidate[0]
    $arguments = @()
    if ($Candidate.Count -gt 1) {
        $arguments = $Candidate[1..($Candidate.Count - 1)]
    }

    try {
        & $command @arguments -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 14), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture()" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-Python314 {
    $candidates = @()
    if ($env:PYTHON_BUILD) {
        $candidates += ,@($env:PYTHON_BUILD)
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3.14")
    }
    $candidates += ,@("python")

    foreach ($candidate in $candidates) {
        if (Test-Python314 -Candidate $candidate) {
            return $candidate
        }
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv python install 3.14 | Out-Host
        $uvPython = (uv python find 3.14).Trim()
        if ($uvPython) {
            $candidate = @($uvPython)
            if (Test-Python314 -Candidate $candidate) {
                return $candidate
            }
        }
    }

    throw "Python 3.14 x64 is required to build the Windows release."
}

function Invoke-Python {
    param(
        [string[]]$PythonCommand,
        [string[]]$Arguments
    )

    $command = $PythonCommand[0]
    $prefix = @()
    if ($PythonCommand.Count -gt 1) {
        $prefix = $PythonCommand[1..($PythonCommand.Count - 1)]
    }
    & $command @prefix @Arguments
}

function Test-BuildVenv {
    param([string]$PythonPath)

    if (!(Test-Path -LiteralPath $PythonPath)) {
        return $false
    }
    & $PythonPath -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 14), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture()" 2>$null
    return $LASTEXITCODE -eq 0
}

function Reset-BuildVenv {
    param([string]$BuildVenv)

    if (!(Test-Path -LiteralPath $BuildVenv)) {
        return
    }

    $resolvedVenv = Resolve-Path -LiteralPath $BuildVenv
    $resolvedRepo = Resolve-Path -LiteralPath $RepoRoot
    if (!$resolvedVenv.Path.StartsWith($resolvedRepo.Path, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove build venv outside repo: $($resolvedVenv.Path)"
    }
    Remove-Item -LiteralPath $resolvedVenv.Path -Recurse -Force
}

function Assert-ReleaseTreeClean {
    param([string]$Stage)

    $forbidden = @(
        "\\.git\\",
        "\\debug\\",
        "\\screenshots\\",
        "\\__pycache__\\",
        "\\.pytest_cache\\",
        "\\_merge_backup",
        "\\web_gui\\uploads\\",
        "paste_state\.json$",
        "\\samples\\.*\.json$",
        "\\samples\\.*\.png$",
        "\.env($|\.)",
        "\.log$"
    )

    $bad = @()
    foreach ($file in Get-ChildItem -LiteralPath $Stage -Recurse -Force -File) {
        $relative = $file.FullName.Substring($Stage.Length).TrimStart([char[]]@("\", "/"))
        foreach ($pattern in $forbidden) {
            if ($relative -match $pattern) {
                $bad += $relative
                break
            }
        }
    }

    if ($bad.Count -gt 0) {
        throw "Release tree contains forbidden files:`n$($bad -join "`n")"
    }
}

$ReleaseVersion = Get-ReleaseVersion -RequestedVersion $Version
$ShouldBuild = !$NoBuild

if ($ShouldBuild) {
    $BuildVenv = Join-Path $RepoRoot ".venv-build"
    $BuildPython = Join-Path $BuildVenv "Scripts\python.exe"

    if (!(Test-BuildVenv -PythonPath $BuildPython)) {
        Reset-BuildVenv -BuildVenv $BuildVenv
        $selectedPython = Get-Python314
        Invoke-Python -PythonCommand $selectedPython -Arguments @("-m", "venv", $BuildVenv)
    }

    & $BuildPython -c "import platform, struct, sys; assert sys.version_info[:2] == (3, 14), sys.version; assert struct.calcsize('P') * 8 == 64, platform.architecture(); print(sys.version)"
    & $BuildPython -m pip install --upgrade pip setuptools wheel
    & $BuildPython -m pip install -r requirements.txt
    & $BuildPython -m pip install -r requirements-build.txt
    & $BuildPython -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 QtWebEngine import OK')"
    & $BuildPython -m py_compile gui.py bot_controller.py cocbot\io.py cocbot\actions.py cocbot\__main__.py cocbot\loop.py
    & $BuildPython -m PyInstaller --noconfirm --clean CoCBot.spec
}

$BuiltDir = Join-Path $RepoRoot "dist\Coc-farm"
$BuiltExe = Join-Path $BuiltDir "Coc-farm.exe"
$BuiltInternal = Join-Path $BuiltDir "_internal"
if (!(Test-Path -LiteralPath $BuiltExe)) {
    throw "Missing build output: $BuiltExe"
}
if (!(Test-Path -LiteralPath $BuiltInternal)) {
    throw "Missing bundled runtime folder: $BuiltInternal"
}

$OutRoot = Join-Path $RepoRoot $OutputDir
$Stage = Join-Path $OutRoot "CoC-Farm-Bot-Windows"
$ZipPath = Join-Path $OutRoot "CoC-Farm-Bot-Windows.zip"
$ChecksumPath = "$ZipPath.sha256"

New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null
if (Test-Path -LiteralPath $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Copy-Item -LiteralPath $BuiltInternal -Destination (Join-Path $Stage "_internal") -Recurse -Force
Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $Stage "CoC Farm Bot.exe") -Force

$releaseFiles = @(
    @("release_assets\QUICK_START.txt", "QUICK_START.txt"),
    @("release_assets\settings.example.json", "settings.example.json"),
    @("release_assets\CHANGELOG.txt", "CHANGELOG.txt"),
    @("README.md", "README.md")
)
foreach ($entry in $releaseFiles) {
    $source = Join-Path $RepoRoot $entry[0]
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $Stage $entry[1]) -Force
    }
}

$commit = ""
try {
    $commit = (& git rev-parse --short HEAD 2>$null).Trim()
} catch {
    $commit = "unknown"
}

@"
CoC Farm Bot Windows Release
Version: $ReleaseVersion
Commit: $commit
Built: $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss K"))

Run CoC Farm Bot.exe from this folder. Keep _internal next to the EXE.
Python and pip are not required on the user's machine.
"@ | Set-Content -LiteralPath (Join-Path $Stage "RELEASE_INFO.txt") -Encoding ASCII

$requiredRuntimeFiles = @(
    "_internal\python314.dll",
    "_internal\web_gui\CoC Farm Bot.dc.html",
    "_internal\web_gui\support.js",
    "_internal\templates\logo.ico"
)
foreach ($relative in $requiredRuntimeFiles) {
    $path = Join-Path $Stage $relative
    if (!(Test-Path -LiteralPath $path)) {
        throw "Missing required bundled runtime asset: $relative"
    }
}

Assert-ReleaseTreeClean -Stage $Stage

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
if (Test-Path -LiteralPath $ChecksumPath) {
    Remove-Item -LiteralPath $ChecksumPath -Force
}

Compress-Archive -LiteralPath $Stage -DestinationPath $ZipPath -Force
$hash = Get-FileHash -Path $ZipPath -Algorithm SHA256
"$($hash.Hash)  CoC-Farm-Bot-Windows.zip" | Set-Content -LiteralPath $ChecksumPath -Encoding ASCII

Write-Host "Created $ZipPath"
Write-Host "Created $ChecksumPath"
Write-Host "Release version: $ReleaseVersion"
