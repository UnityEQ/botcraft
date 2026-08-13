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
Get-Content -LiteralPath $resolved -Raw | browser-use
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
