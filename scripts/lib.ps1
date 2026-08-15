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
    param([string]$Name = "default")
    if ($env:BU_NAME) { $Name = $env:BU_NAME }
    try {
        $python = Get-HarnessPython
    } catch {
        return $false
    }
    $safe = $Name -replace "'", ""
    & $python -c "from browser_harness._ipc import ping; import sys; sys.exit(0 if ping('$safe', timeout=1.0) else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-BotcraftChromeDir {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Join-Path $env:LOCALAPPDATA "botcraft-chrome\$Name"
}

function Get-BotcraftChromePort {
    param([Parameter(Mandatory = $true)][string]$Name)
    $dir = Get-BotcraftChromeDir $Name
    foreach ($file in @((Join-Path $dir "cdp-port.txt"), (Join-Path $dir "DevToolsActivePort"))) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        try {
            $raw = (Get-Content -LiteralPath $file -TotalCount 1 -ErrorAction Stop).Trim()
        } catch { continue }
        $p = 0
        if ([int]::TryParse($raw, [ref]$p) -and $p -gt 0) { return $p }
    }
    return $null
}

function Save-BotcraftChromePort {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $dir = Get-BotcraftChromeDir $Name
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -LiteralPath (Join-Path $dir "cdp-port.txt") -Value "$Port" -NoNewline
}

function Test-TcpPortOpen {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $Port)
        $c.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-ChromeUserDataDir {
    return Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
}

function Get-MainChromeCdpUrl {
    # Official Chrome only — never botcraft-chrome\<name>.
    $file = Join-Path (Get-ChromeUserDataDir) "DevToolsActivePort"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    $port = 0
    $line = (Get-Content -LiteralPath $file -TotalCount 1).Trim()
    if (-not [int]::TryParse($line, [ref]$port) -or $port -le 0) { return $null }
    if (-not (Test-TcpPortOpen -Port $port)) { return $null }
    return "http://127.0.0.1:$port"
}

function Get-ChromeProfiles {
    $localState = Join-Path (Get-ChromeUserDataDir) "Local State"
    if (-not (Test-Path -LiteralPath $localState)) { return @() }
    $json = Get-Content -LiteralPath $localState -Raw -Encoding UTF8 | ConvertFrom-Json
    $cache = $json.profile.info_cache
    $rows = @()
    if ($cache) {
        $cache.PSObject.Properties | ForEach-Object {
            $dirName = $_.Name
            $info = $_.Value
            $rows += [pscustomobject]@{
                Directory = $dirName
                Name      = if ($info.name) { $info.name } else { $dirName }
            }
        }
    }
    return $rows
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

function Test-WocUserInterrupt {
    param($Code)
    if ($null -eq $Code) { return $false }
    $c = 0
    if (-not [int]::TryParse("$Code", [ref]$c)) { return $false }
    # 130 = hunt Ctrl+C. -1073741510 = Windows STATUS_CONTROL_C_EXIT.
    return ($c -eq 130) -or ($c -eq -1073741510)
}

if (-not ("WocCtrlC" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
public static class WocCtrlC {
    public static volatile bool Stopped = false;
    static bool hooked;
    public static void Hook() {
        if (hooked) return;
        hooked = true;
        try {
            Console.CancelKeyPress += (s, e) => {
                e.Cancel = true;
                Stopped = true;
            };
        } catch {}
    }
    public static void Reset() { Stopped = false; }
}
"@
}

function Register-WocCtrlC {
    try { [WocCtrlC]::Hook() } catch {}
}

function Reset-WocCtrlC {
    # A prior Ctrl+C in this same PowerShell leaves Stopped=true forever.
    try { [WocCtrlC]::Stopped = $false } catch {}
}

function Test-WocStopRequested {
    try { return [WocCtrlC]::Stopped } catch { return $false }
}

function Stop-WocCharacter {
    $root = Split-Path $PSScriptRoot -Parent
    $stop = Join-Path $root "examples\woc_stop.py"
    if (-not (Test-Path -LiteralPath $stop)) { return }
    if (-not (Test-BrowserDaemon)) {
        Write-Host "Could not send stop (daemon down). Tap W or S in the game to cancel autorun."
        return
    }
    Write-Host "Sending stop (clear autorun)"
    Get-Content -LiteralPath $stop -Raw | browser-use | Out-Host
}
