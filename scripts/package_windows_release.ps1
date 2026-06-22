param(
    [switch]$Build,
    [switch]$NoBuild,
    [string]$Version = "",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$buildScript = Join-Path $PSScriptRoot "build_windows_release.ps1"
$arguments = @()
if ($Build) {
    $arguments += "-Build"
}
if ($NoBuild) {
    $arguments += "-NoBuild"
}
if (![string]::IsNullOrWhiteSpace($Version)) {
    $arguments += @("-Version", $Version)
}
if (![string]::IsNullOrWhiteSpace($OutputDir)) {
    $arguments += @("-OutputDir", $OutputDir)
}

& $buildScript @arguments
