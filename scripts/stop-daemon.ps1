$ErrorActionPreference = "Continue"
. "$PSScriptRoot\lib.ps1"

if (Get-Command browser-use -ErrorAction SilentlyContinue) {
    browser-use --reload 2>$null | Out-Null
}

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'browser_harness\.daemon' } |
    ForEach-Object {
        Write-Host "Stopping daemon PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Remove-Item -LiteralPath $script:PidFile, $script:PortFile -ErrorAction SilentlyContinue
Write-Host "Daemon stopped."
