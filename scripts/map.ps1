# Install or refresh NPC squares + mouseover on the live World of ClaudeCraft map.
# Fully separate from the hunt. Re-run after a page reload.
#
#   .\scripts\map.ps1
#   .\scripts\map.ps1 -Player CharacterName
#   .\scripts\map.ps1 -Name salty -Player salty

param(
    [string]$Player = "",
    [string]$Name = "",
    [string]$CdpUrl = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib.ps1"
$root = Split-Path $PSScriptRoot -Parent
$script = Join-Path $root "examples\woc_map_npcs.py"

if ($Player) {
    $env:WOC_PLAYER = $Player
} elseif ($Name) {
    $env:WOC_PLAYER = $Name
} else {
    Remove-Item Env:WOC_PLAYER -ErrorAction SilentlyContinue
}

if ($Name) {
    $env:BU_NAME = $Name
    if ($CdpUrl) { $env:BU_CDP_URL = $CdpUrl }
    if (-not $env:BU_CDP_URL) {
        $savedPort = Get-BotcraftChromePort -Name $Name
        if ($savedPort) { $env:BU_CDP_URL = "http://127.0.0.1:$savedPort" }
    }
} else {
    Remove-Item Env:BU_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:BU_CDP_WS -ErrorAction SilentlyContinue
    if ($CdpUrl) {
        $env:BU_CDP_URL = $CdpUrl
    } else {
        $main = Get-MainChromeCdpUrl
        if ($main) {
            $env:BU_CDP_URL = $main
        } else {
            Remove-Item Env:BU_CDP_URL -ErrorAction SilentlyContinue
        }
    }
}

Write-Host "Map overlay - attaching to the ClaudeCraft tab"
if ($env:WOC_PLAYER) { Write-Host "Pinned character: $($env:WOC_PLAYER)" }
if ($env:BU_NAME) {
    Write-Host "Daemon name: $($env:BU_NAME)"
} else {
    Write-Host "Daemon name: default (everyday Chrome profile, not start-chrome)"
}
if ($env:BU_CDP_URL) { Write-Host "CDP: $($env:BU_CDP_URL)" }
& "$PSScriptRoot\run.ps1" $script
exit $LASTEXITCODE
