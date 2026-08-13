$ErrorActionPreference = "Stop"

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Error "Google Chrome was not found."
}

Start-Process -FilePath $chrome -ArgumentList "chrome://inspect/#remote-debugging"
Write-Host "Opened chrome://inspect/#remote-debugging"
Write-Host "Tick 'Allow remote debugging for this browser instance'."
Write-Host "Click Allow if Chrome shows a remote-debugging popup."
Write-Host "Then run: .\scripts\check-setup.ps1"
