[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$manifestPath = Join-Path $repoRoot ".codex-plugin\plugin.json"

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Codex plugin manifest not found: $manifestPath"
}

$userHome = $env:USERPROFILE
if ([string]::IsNullOrWhiteSpace($userHome)) {
    $userHome = [Environment]::GetFolderPath("UserProfile")
}

$codexHome = $env:CODEX_HOME
if ([string]::IsNullOrWhiteSpace($codexHome)) {
    $codexHome = Join-Path $userHome ".codex"
    $env:CODEX_HOME = $codexHome
}

if ([string]::IsNullOrWhiteSpace($env:HOME)) {
    $env:HOME = $userHome
}

$cachebusterScript = Join-Path $codexHome "skills\.system\plugin-creator\scripts\update_plugin_cachebuster.py"

if (-not (Test-Path -LiteralPath $cachebusterScript)) {
    throw "Codex plugin cachebuster helper not found: $cachebusterScript"
}

$pluginName = (Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json).name
if ([string]::IsNullOrWhiteSpace($pluginName)) {
    throw "Plugin name is missing from $manifestPath"
}

Get-Command python -ErrorAction Stop | Out-Null
Get-Command codex -ErrorAction Stop | Out-Null

Write-Host "Updating cachebuster for $pluginName..."
& python $cachebusterScript $repoRoot
if ($LASTEXITCODE -ne 0) {
    throw "Cachebuster update failed with exit code $LASTEXITCODE"
}

Write-Host "Reinstalling $pluginName@personal..."
& codex plugin add "$pluginName@personal"
if ($LASTEXITCODE -ne 0) {
    throw "Plugin reinstall failed with exit code $LASTEXITCODE"
}

Write-Host "Done. Start a new Codex task to load the updated plugin."
