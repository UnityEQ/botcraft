$ErrorActionPreference = "Continue"
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"

Write-Host "=== PATH (uv tools) ==="
Write-Host "$env:USERPROFILE\.local\bin"
Write-Host ""

Write-Host "=== browser-use ==="
if (Get-Command browser-use -ErrorAction SilentlyContinue) {
    browser-use --version
} else {
    Write-Host "MISSING. Install: uv tool install --python 3.12 --upgrade --force browser-use"
}

Write-Host ""
Write-Host "=== Chrome ==="
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$found = $false
foreach ($p in $chromePaths) {
    if (Test-Path $p) {
        Write-Host "FOUND: $p"
        $found = $true
        break
    }
}
if (-not $found) {
    Write-Host "Google Chrome not found in the usual install locations."
}

Write-Host ""
Write-Host "=== doctor ==="
if (Get-Command browser-use -ErrorAction SilentlyContinue) {
    browser-use --doctor
} else {
    Write-Host "skipped (CLI missing)"
}
