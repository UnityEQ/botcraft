# Shared paths and Windows job-breakaway launch for the Browser Use daemon.

$script:UvBin = Join-Path $env:USERPROFILE ".local\bin"
$env:PATH = "$script:UvBin;$env:PATH"

$script:HarnessPython = Join-Path $env:APPDATA "uv\tools\browser-use\Scripts\python.exe"
$script:RuntimeDir = Join-Path $env:USERPROFILE ".config\browser-harness\runtime"
$script:PidFile = Join-Path $script:RuntimeDir "bu-default.pid"
$script:PortFile = Join-Path $script:RuntimeDir "bu-default.port"

function Get-HarnessPython {
    if (Test-Path -LiteralPath $script:HarnessPython) {
        return $script:HarnessPython
    }
    throw "browser-use Python not found at $script:HarnessPython. Install with: uv tool install --python 3.12 --upgrade --force browser-use"
}

function Test-BrowserDaemon {
    try {
        $python = Get-HarnessPython
    } catch {
        return $false
    }
    & $python -c "from browser_harness._ipc import ping; import sys; sys.exit(0 if ping('default', timeout=1.0) else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

function Start-DetachedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )
    # Grok's shell runs commands inside a Windows Job Object. Child processes
    # started with Popen die when the command ends. Win32_Process.Create starts
    # outside that job, so the daemon can keep the single Chrome CDP connection.
    $cmd = '"' + $FilePath + '"'
    if ($ArgumentList.Count -gt 0) {
        $quoted = $ArgumentList | ForEach-Object {
            if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
        }
        $cmd = "$cmd $($quoted -join ' ')"
    }
    $proc = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $cmd
    }
    if ($proc.ReturnValue -ne 0 -or -not $proc.ProcessId) {
        throw "Failed to start detached process (WMI return $($proc.ReturnValue)): $cmd"
    }
    return $proc.ProcessId
}
