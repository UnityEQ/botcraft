# Start the Browser Use daemon outside Grok's job so it keeps one Chrome
# connection. Click Allow once. Later commands reuse this process.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib.ps1"

if (Test-BrowserDaemon) {
    Write-Host "Daemon is already running. No new Allow popup needed."
    exit 0
}

$python = Get-HarnessPython
$pidStarted = Start-DetachedProcess -FilePath $python -ArgumentList @("-m", "browser_harness.daemon")
Write-Host "Started daemon PID $pidStarted"
Write-Host "If Chrome shows 'Allow remote debugging?', click Allow once."
Write-Host "Waiting for the daemon to come up..."

$deadline = (Get-Date).AddSeconds(50)
while ((Get-Date) -lt $deadline) {
    if (Test-BrowserDaemon) {
        Write-Host "Daemon is up and holding the Chrome connection."
        Write-Host "You should not see another Allow popup until Chrome or this daemon restarts."
        exit 0
    }
    Start-Sleep -Milliseconds 400
}

Write-Host "Daemon did not report healthy yet."
Write-Host "Click Allow in Chrome if a popup is waiting, then run: .\scripts\check-setup.ps1"
exit 1
