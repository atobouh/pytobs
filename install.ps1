# pytobs installer for Windows.
#   irm https://raw.githubusercontent.com/atobouh/pytobs/main/install.ps1 | iex
# Optional: $env:PYTOBS_REF = "some-branch" before running, to install a branch or tag.

$ErrorActionPreference = "Stop"
$ref = if ($env:PYTOBS_REF) { $env:PYTOBS_REF } else { "main" }
$source = "git+https://github.com/atobouh/pytobs@$ref"

function Step($text) { Write-Host "  $text" -ForegroundColor DarkGray }
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$user;$machine;$env:USERPROFILE\.local\bin"
}

Write-Host ""
Write-Host "  pytobs" -ForegroundColor White
Write-Host ""

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Step "installing uv (Python tool manager)"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    Refresh-Path
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Step "installing Git (needed to download pytobs)"
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Refresh-Path
        $env:Path += ";$env:ProgramFiles\Git\cmd"
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "  Git is required. Install it from https://git-scm.com/download/win and run this again." -ForegroundColor Red
        return
    }
}

Step "installing pytobs from $ref"
uv tool install --force --compile-bytecode --python 3.13 $source
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Install failed. If the repository is private, sign in to GitHub when Git asks, then retry." -ForegroundColor Red
    return
}
uv tool update-shell | Out-Null
Refresh-Path

Step "setting up font, Windows Terminal profile and menus"
pytobs --setup
