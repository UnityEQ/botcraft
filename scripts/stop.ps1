# Clear autorun / held W if a hunt was killed mid-step.
#
#   .\scripts\stop.ps1
#   .\scripts\stop.ps1 -Name alt -Player CharacterName

param(
    [string]$Player = "",
    [string]$Name = "",
    [string]$CdpUrl = ""
)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\lib.ps1"
$root = Split-Path $PSScriptRoot -Parent
$stop = Join-Path $root "examples\woc_stop.py"

if ($Player) {
    $env:WOC_PLAYER = $Player
} elseif ($Name) {
    $env:WOC_PLAYER = $Name
}

if ($Name) {
    $env:BU_NAME = $Name
    if ($CdpUrl) { $env:BU_CDP_URL = $CdpUrl }
    if (-not $env:BU_CDP_URL) {
        $savedPort = Get-BotcraftChromePort -Name $Name
        if ($savedPort) { $env:BU_CDP_URL = "http://127.0.0.1:$savedPort" }
    }
} elseif ($CdpUrl) {
    $env:BU_CDP_URL = $CdpUrl
}

if ($env:WOC_PLAYER) { Write-Host "Stop pinned: $($env:WOC_PLAYER)" }
if ($env:BU_NAME) { Write-Host "Daemon name: $($env:BU_NAME)" }
if ($env:BU_CDP_URL) { Write-Host "CDP: $($env:BU_CDP_URL)" }

if (-not (Test-BrowserDaemon)) {
    Write-Host "Daemon not running. Tap W or S in the game to cancel autorun."
    exit 1
}

$env:BOTCRAFT_ROOT = $root
Get-Content -LiteralPath $stop -Raw | browser-use
exit $LASTEXITCODE
