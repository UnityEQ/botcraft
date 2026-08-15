# Keep the hunt loop running. browser-use or Chrome CDP can drop the
# process; this relaunches until you press Ctrl+C.
#
# One character (current Chrome):
#   .\scripts\hunt.ps1
#   .\scripts\hunt.ps1 -Player CharacterName
#
# Second character at the same time — other Chrome instance + named daemon:
#   .\scripts\start-chrome.ps1 -Name alt
#   log in on that window, then:
#   .\scripts\hunt.ps1 -Name alt -Player OtherName
#
# Home is wherever that character is standing when this script starts.

param(
    [string]$Player = "",
    [string]$Name = "",
    [string]$CdpUrl = ""
)

$ErrorActionPreference = "Continue"
. "$PSScriptRoot\lib.ps1"
$root = Split-Path $PSScriptRoot -Parent
$hunt = Join-Path $root "examples\woc_hunt_loop.py"

if ($Player) {
    $env:WOC_PLAYER = $Player
} elseif ($Name) {
    # Named Chrome is that character. Do not keep a leftover WOC_PLAYER from this shell.
    $env:WOC_PLAYER = $Name
} else {
    Remove-Item Env:WOC_PLAYER -ErrorAction SilentlyContinue
}

# A prior start-chrome in this same PowerShell leaves BU_NAME / BU_CDP_URL set.
# hunt.ps1 -Player X (no -Name) must use the normal Chrome, not that leftover.
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

Write-Host "Hunt watchdog. Start position in the game is the safespot."
if ($env:WOC_PLAYER) { Write-Host "Pinned character: $($env:WOC_PLAYER)" }
if ($env:BU_NAME) {
    Write-Host "Daemon name: $($env:BU_NAME)"
} else {
    Write-Host "Daemon name: default (everyday Chrome profile, not start-chrome)"
}
if ($env:BU_CDP_URL) { Write-Host "CDP: $($env:BU_CDP_URL)" }
Write-Host "Ctrl+C stops the watchdog and clears autorun."
Write-Host "If they keep running after a close: .\scripts\stop.ps1"

Register-WocCtrlC
Reset-WocCtrlC

try {
    while (-not (Test-WocStopRequested)) {
        Write-Host ""
        Write-Host "HUNT start $(Get-Date -Format 'HH:mm:ss')"
        & "$PSScriptRoot\run.ps1" $hunt
        $code = $LASTEXITCODE
        if ($code -eq 2) {
            Write-Host "HUNT stopped: character died"
            exit 2
        }
        if ((Test-WocStopRequested) -or (Test-WocUserInterrupt $code) -or ($code -eq 0)) {
            Write-Host "HUNT stopped"
            break
        }
        Write-Host "HUNT exited code $code at $(Get-Date -Format 'HH:mm:ss') - restarting in 3s"
        Start-Sleep -Seconds 3
    }
} finally {
    Stop-WocCharacter
}
