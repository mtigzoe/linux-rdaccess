# Disable Linux Orca Remote auto-connect via the saved Windows SSH profile.
# This does not disconnect or close the Windows NVDA add-on.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$controller = Join-Path $repoRoot 'linux_rdaccess_windows.py'
if (-not (Test-Path -LiteralPath $controller -PathType Leaf)) {
    Write-Error 'Windows controller file was not found.'
    exit 1
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is required and must be in PATH.'
    exit 1
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Error 'Windows OpenSSH (ssh) is required.'
    exit 1
}
Push-Location $repoRoot
try {
    & uv run --no-project python $controller disconnect
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host 'Linux Orca Remote auto-connect disabled.'
    exit 0
}
finally {
    Pop-Location
}
