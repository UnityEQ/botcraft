# Keep the wolf/hunt loop running. browser-use or Chrome CDP can drop the
# process; this relaunches until you press Ctrl+C.

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$hunt = Join-Path $root "examples\woc_hunt_loop.py"

Write-Host "Hunt watchdog. Start position in the game is the safespot."
Write-Host "Ctrl+C stops the watchdog and the current run."

while ($true) {
    Write-Host ""
    Write-Host "HUNT start $(Get-Date -Format 'HH:mm:ss')"
    & "$PSScriptRoot\run.ps1" $hunt
    $code = $LASTEXITCODE
    Write-Host "HUNT exited code $code at $(Get-Date -Format 'HH:mm:ss') - restarting in 3s"
    Start-Sleep -Seconds 3
}
