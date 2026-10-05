param(
	[switch]$Uninstall,
	[string]$NvdaConfigPath = (Join-Path $env:APPDATA "nvda")
)

$ErrorActionPreference = "Stop"
$addonName = "linuxRdaccessSpeechProbe"
$targetRoot = Join-Path $NvdaConfigPath "addons\$addonName"
$sourceRoot = Join-Path $PSScriptRoot "nvda_speech_probe"

if ($Uninstall) {
	if (Test-Path $targetRoot) {
		Remove-Item -Recurse -Force $targetRoot
	}
	Write-Host "Removed $addonName. Restart NVDA."
	exit 0
}

if (-not (Test-Path (Join-Path $sourceRoot "manifest.ini"))) {
	throw "Speech probe source files were not found next to this installer."
}

if (Test-Path $targetRoot) {
	Remove-Item -Recurse -Force $targetRoot
}

$pluginTarget = Join-Path $targetRoot "globalPlugins\linuxRdaccessSpeechProbe"
New-Item -ItemType Directory -Force -Path $pluginTarget | Out-Null
Copy-Item -Force -Path (Join-Path $sourceRoot "manifest.ini") -Destination (Join-Path $targetRoot "manifest.ini")
Copy-Item -Force -Path (Join-Path $sourceRoot "globalPlugins\linuxRdaccessSpeechProbe\__init__.py") -Destination (Join-Path $pluginTarget "__init__.py")
Copy-Item -Force -Path (Join-Path $sourceRoot "globalPlugins\linuxRdaccessSpeechProbe\shared.py") -Destination (Join-Path $pluginTarget "shared.py")

Write-Host "Installed $addonName."
Write-Host "Restart NVDA, then press NVDA+Ctrl+Shift+F12 to enable or disable the probe."
Write-Host "Speech is sent only to Windows localhost:8765 and only while the probe is enabled."
