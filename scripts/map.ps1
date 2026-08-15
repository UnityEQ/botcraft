# Install or refresh NPC squares + mouseover on the live World of ClaudeCraft map.
# Fully separate from the hunt. Re-run after a page reload.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$script = Join-Path $root "examples\woc_map_npcs.py"

Write-Host "Map overlay - attaching to the ClaudeCraft tab"
& "$PSScriptRoot\run.ps1" $script
exit $LASTEXITCODE
