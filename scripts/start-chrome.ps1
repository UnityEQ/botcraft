# Second Chrome instance for a second hunt. This is NOT your normal Chrome -
# it has its own folder so it can have its own debug port.
#
# First time (optional: copy an existing profile so you keep that Google login):
#   .\scripts\start-chrome.ps1 -Name alt -ListProfiles
#   .\scripts\start-chrome.ps1 -Name alt -CloneProfile "Default"
#
# Later sessions - only if that window is closed:
#   .\scripts\start-chrome.ps1 -Name alt
# Then:
#   .\scripts\hunt.ps1 -Name alt -Player OtherName
#
# You do not re-clone every time. The alt folder keeps the login.

param(
    [Parameter(Mandatory = $true)][string]$Name,
    [int]$Port = 0,
    [switch]$ListProfiles,
    [string]$CloneProfile = ""
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib.ps1"

if ($Name -notmatch '^[A-Za-z0-9_-]{1,32}$') {
    throw "Name must be letters, numbers, _ or -"
}

if ($ListProfiles) {
    Write-Host "Profiles in your normal Chrome:"
    $rows = Get-ChromeProfiles
    if (-not $rows) {
        Write-Host "  (none found - is Chrome installed and have you signed in once?)"
    } else {
        $rows | ForEach-Object { Write-Host ("  {0,-16}  {1}" -f $_.Directory, $_.Name) }
        Write-Host ""
        Write-Host "Clone one into this instance (once):"
        Write-Host "  .\scripts\start-chrome.ps1 -Name $Name -CloneProfile `"Default`""
    }
}

$saved = Get-BotcraftChromePort -Name $Name
if ($Port -le 0) {
    if ($saved) {
        $Port = $saved
    } else {
        $hash = 0
        foreach ($ch in $Name.ToCharArray()) { $hash = ($hash * 33 + [int]$ch) -band 0x7fffffff }
        $Port = 9222 + ($hash % 80) + 1
    }
}

$dir = Get-BotcraftChromeDir $Name
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Save-BotcraftChromePort -Name $Name -Port $Port

if ($CloneProfile) {
    $src = Join-Path (Get-ChromeUserDataDir) $CloneProfile
    $dest = Join-Path $dir "Default"
    if (-not (Test-Path -LiteralPath $src)) {
        throw "Chrome profile folder not found: $src  (run -ListProfiles)"
    }
    Write-Host "Copying Chrome profile '$CloneProfile' into $dest"
    Write-Host "(Close that profile in normal Chrome if copy errors appear.)"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & robocopy $src $dest /E /XD Cache "Code Cache" GPUCache "GrShaderCache" "ShaderCache" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        Write-Host "robocopy exit $rc - some files were locked. Log in manually if this profile looks empty."
    }
}

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "Google Chrome not found" }

$lock = Join-Path $dir "lockfile"
$alreadyOpen = Test-Path -LiteralPath $lock
if (Test-TcpPortOpen -Port $Port) {
    Write-Host "Chrome '$Name' already listening on port $Port - not launching another."
} elseif ($alreadyOpen) {
    Write-Host "Chrome '$Name' is already open but debugging is off."
    Write-Host "Close that window completely (all its tabs), then run this script again."
    Write-Host "Opening a second copy of the same profile will not enable the hunt port."
    exit 1
} else {
    Write-Host "Starting Chrome '$Name' on port $Port"
    Write-Host "This window is a separate Chrome. Your usual profile picker is not here."
    Write-Host "User data: $dir"
    Start-Process -FilePath $chrome -ArgumentList @(
        "--user-data-dir=$dir",
        "--remote-debugging-port=$Port",
        "--remote-allow-origins=*",
        "https://worldofclaudecraft.com/"
    )
}

$env:BU_NAME = $Name
$env:BU_CDP_URL = "http://127.0.0.1:$Port"
Write-Host ""
Write-Host "Then:"
Write-Host "  .\scripts\start-daemon.ps1 -Name $Name"
Write-Host "  .\scripts\hunt.ps1 -Name $Name -Player YourOtherCharacter"
Write-Host ""
Write-Host "Next time: if this window is still open, skip start-chrome and just hunt.ps1 -Name $Name"
