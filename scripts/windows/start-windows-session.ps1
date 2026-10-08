# Start the Linux accessibility bridge from Windows using the saved SSH profile.
# This script does not start or control the NVDA Remote Access add-on.
[CmdletBinding()]
param(
    [switch]$Configure,
    [switch]$SkipStatus
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$controller = Join-Path $repoRoot 'linux_rdaccess_windows.py'
if (-not (Test-Path -LiteralPath $controller -PathType Leaf)) {
    Write-Error 'Windows controller file was not found.'
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is required. Install uv and make sure it is in PATH.'
    exit 1
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Error 'Windows OpenSSH (ssh) is required.'
    exit 1
}
Push-Location $repoRoot
try {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & uv venv
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $settings = Join-Path $env:APPDATA 'linux-rdaccess\windows-config.json'
    if ($Configure -or -not (Test-Path -LiteralPath $settings)) {
        Write-Host 'Configure the Linux SSH connection.'
        & uv run --no-project python $controller configure
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host 'Starting the Linux accessibility bridge over SSH...'
    & uv run --no-project python $controller connect
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $SkipStatus) {
        & uv run --no-project python $controller status
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host 'Linux command completed. Check the NVDA Remote Access connection separately.'
    exit 0
}
finally {
    Pop-Location
}
