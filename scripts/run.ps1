param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib.ps1"

$env:BOTCRAFT_ROOT = Split-Path $PSScriptRoot -Parent

if (-not (Get-Command browser-use -ErrorAction SilentlyContinue)) {
    Write-Error "browser-use is not on PATH. Install with: uv tool install --python 3.12 --upgrade --force browser-use"
}

if (-not (Test-BrowserDaemon)) {
    Write-Host "Daemon not running - starting it. Click Allow in Chrome if a popup appears."
    & "$PSScriptRoot\start-daemon.ps1"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$resolved = Resolve-Path -LiteralPath $Script
$isHunt = [System.IO.Path]::GetFileName("$resolved") -eq "woc_hunt_loop.py"
if ($isHunt) {
    $env:WOC_HALT_ON_EXIT = "1"
} else {
    $env:WOC_HALT_ON_EXIT = "0"
}

Register-WocCtrlC
Reset-WocCtrlC

do {
    if (Test-WocStopRequested) { break }
    if (-not (Test-BrowserDaemon)) {
        Write-Host "Daemon not running - starting it. Click Allow in Chrome if a popup appears."
        & "$PSScriptRoot\start-daemon.ps1"
    }
    Get-Content -LiteralPath $resolved -Raw | browser-use
    $code = $LASTEXITCODE
    if ($isHunt) {
        Stop-WocCharacter
    }
    if (-not $isHunt) {
        if ($code -ne 0) { exit $code }
        break
    }
    if ($code -eq 2) {
        Write-Host "Hunt stopped: character died (exit $code)"
        exit 2
    }
    if ((Test-WocStopRequested) -or (Test-WocUserInterrupt $code)) {
        Write-Host "Hunt stopped by you"
        exit 0
    }
    Write-Host "Hunt process exited code $code at $(Get-Date -Format 'HH:mm:ss') - restarting in 3s (Ctrl+C to stop)"
    Start-Sleep -Seconds 3
} while ($true)

if ($isHunt) {
    Stop-WocCharacter
}
