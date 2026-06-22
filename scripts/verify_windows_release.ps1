param(
    [string]$ZipPath = "",
    [string]$VerifyDir = "C:\CoCFarmBotFinalVerify",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ([string]::IsNullOrWhiteSpace($ZipPath)) {
    $ZipPath = Join-Path $RepoRoot "dist\CoC-Farm-Bot-Windows.zip"
}

if (!(Test-Path -LiteralPath $ZipPath)) {
    throw "Missing release ZIP: $ZipPath"
}

$resolvedVerifyParent = Split-Path -Parent $VerifyDir
if (!(Test-Path -LiteralPath $resolvedVerifyParent)) {
    New-Item -ItemType Directory -Force -Path $resolvedVerifyParent | Out-Null
}

if (Test-Path -LiteralPath $VerifyDir) {
    $leaf = Split-Path -Leaf $VerifyDir
    if ($leaf -ne "CoCFarmBotFinalVerify") {
        throw "Refusing to remove unexpected verify directory: $VerifyDir"
    }
    Remove-Item -LiteralPath $VerifyDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $VerifyDir | Out-Null

Expand-Archive -LiteralPath $ZipPath -DestinationPath $VerifyDir -Force

$ReleaseRoot = Join-Path $VerifyDir "CoC-Farm-Bot-Windows"
$ExePath = Join-Path $ReleaseRoot "CoC Farm Bot.exe"
$InternalDir = Join-Path $ReleaseRoot "_internal"

$required = @(
    $ExePath,
    $InternalDir,
    (Join-Path $InternalDir "python314.dll"),
    (Join-Path $InternalDir "web_gui\CoC Farm Bot.dc.html"),
    (Join-Path $InternalDir "web_gui\support.js"),
    (Join-Path $InternalDir "templates\logo.ico"),
    (Join-Path $ReleaseRoot "QUICK_START.txt")
)

foreach ($path in $required) {
    if (!(Test-Path -LiteralPath $path)) {
        throw "Missing required extracted file: $path"
    }
}

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
foreach ($file in Get-ChildItem -LiteralPath $ReleaseRoot -Recurse -Force -File) {
    $relative = $file.FullName.Substring($ReleaseRoot.Length).TrimStart([char[]]@("\", "/"))
    foreach ($pattern in $forbidden) {
        if ($relative -match $pattern) {
            $bad += $relative
            break
        }
    }
}
if ($bad.Count -gt 0) {
    throw "Extracted release contains forbidden files:`n$($bad -join "`n")"
}

if (!$NoLaunch) {
    $oldPythonHome = $env:PYTHONHOME
    $oldPythonPath = $env:PYTHONPATH
    $oldPath = $env:Path
    $proc = $null
    try {
        $env:PYTHONHOME = $null
        $env:PYTHONPATH = $null
        $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"

        $proc = Start-Process -FilePath $ExePath -WorkingDirectory $ReleaseRoot -PassThru
        Start-Sleep -Seconds 10
        $proc.Refresh()

        if ($proc.HasExited) {
            throw "EXE exited during smoke test with code $($proc.ExitCode)"
        }
        if ($proc.MainWindowHandle -eq 0) {
            throw "EXE is running but no GUI window handle was detected"
        }

        Write-Host "GUI smoke test window: $($proc.MainWindowTitle)"
    } finally {
        if ($proc -and !$proc.HasExited) {
            $null = $proc.CloseMainWindow()
            Start-Sleep -Seconds 2
            $proc.Refresh()
            if (!$proc.HasExited) {
                Stop-Process -Id $proc.Id -Force
            }
        }
        $env:PYTHONHOME = $oldPythonHome
        $env:PYTHONPATH = $oldPythonPath
        $env:Path = $oldPath
    }
}

Write-Host "Verified release ZIP: $ZipPath"
Write-Host "Extracted to: $VerifyDir"
