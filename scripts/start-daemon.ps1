# Start the Browser Use daemon outside Grok's job so it keeps one Chrome
# connection. Click Allow once. Later commands reuse this process.
#
# Second character:  .\scripts\start-daemon.ps1 -Name alt
# (set BU_CDP_URL first if that Chrome is on another debugging port)

param(
    [string]$Name = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib.ps1"

if ($Name) { $env:BU_NAME = $Name }
$daemonName = if ($env:BU_NAME) { $env:BU_NAME } else { "default" }

# Default daemon must attach to everyday Chrome, not botcraft-chrome\<name>.
if ($daemonName -eq "default" -and -not $env:BU_CDP_URL -and -not $env:BU_CDP_WS) {
    $main = Get-MainChromeCdpUrl
    if ($main) { $env:BU_CDP_URL = $main }
}

if (Test-BrowserDaemon -Name $daemonName) {
    Write-Host "Daemon '$daemonName' is already running. No new Allow popup needed."
    exit 0
}

$python = Get-HarnessPython
# WMI Create does not inherit this shell's env. Bake BU_* into the command line.
$prefix = "set `"BU_NAME=$daemonName`""
if ($env:BU_CDP_URL) { $prefix = "$prefix && set `"BU_CDP_URL=$($env:BU_CDP_URL)`"" }
if ($env:BU_CDP_WS) { $prefix = "$prefix && set `"BU_CDP_WS=$($env:BU_CDP_WS)`"" }
$cmd = "cmd.exe"
$daemonArgs = @("/c", "$prefix && `"$python`" -m browser_harness.daemon")
$pidStarted = Start-DetachedProcess -FilePath $cmd -ArgumentList $daemonArgs
Write-Host "Started daemon '$daemonName' PID $pidStarted"
Write-Host "If Chrome shows 'Allow remote debugging?', click Allow once."
Write-Host "Waiting for the daemon to come up..."

$deadline = (Get-Date).AddSeconds(50)
while ((Get-Date) -lt $deadline) {
    if (Test-BrowserDaemon -Name $daemonName) {
        Write-Host "Daemon is up and holding the Chrome connection."
        Write-Host "You should not see another Allow popup until Chrome or this daemon restarts."
        exit 0
    }
    Start-Sleep -Milliseconds 400
}

Write-Host "Daemon did not report healthy yet."
Write-Host "Click Allow in Chrome if a popup is waiting, then run: .\scripts\check-setup.ps1"
exit 1
