# One-shot installer for WSL2 + Docker Desktop.
#
# Double-click this file (or run install-docker.cmd). It re-launches itself elevated, which costs
# one UAC approval, then installs WSL2 and Docker Desktop and reports whether a reboot is needed.
#
# Why the AI could not do this: raising the consent prompt requires an interactive user; a
# non-elevated process cannot approve UAC for itself.
#
# The file is intentionally ASCII-only. Windows PowerShell 5.1 reads a .ps1 without a BOM using
# the system ANSI code page, so Chinese text in this file would be garbled and could break the
# parser - which is exactly what happened on the first attempt.

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host 'Requesting administrator permission - click "Yes" on the UAC prompt.' -ForegroundColor Yellow
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath)
    )
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs
    exit
}

Write-Host '=== Administrator permission granted ===' -ForegroundColor Green

# ---------------------------------------------------------------- WSL2
Write-Host ''
Write-Host '[1/3] Installing WSL2 ...' -ForegroundColor Cyan
$wslCommand = Get-Command wsl -ErrorAction SilentlyContinue
$wslReady = $false
if ($wslCommand) {
    $statusText = ''
    try { $statusText = (& wsl --status 2>&1 | Out-String) } catch { $statusText = '' }
    if ($statusText -match '2') { $wslReady = $true }
}
if ($wslReady) {
    Write-Host '  WSL already present, skipping.' -ForegroundColor Green
} else {
    & wsl --install --no-distribution
    Write-Host '  WSL install command finished. A reboot is usually required.'
}

# ---------------------------------------------------------------- Docker Desktop
Write-Host ''
Write-Host '[2/3] Installing Docker Desktop ...' -ForegroundColor Cyan
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    Write-Host '  docker already on PATH, skipping.' -ForegroundColor Green
} else {
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
}

# ---------------------------------------------------------------- verify
Write-Host ''
Write-Host '[3/3] Verifying ...' -ForegroundColor Cyan
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    & docker --version
    Write-Host '  Docker CLI found. Start Docker Desktop, then run: docker compose version' -ForegroundColor Green
} else {
    Write-Host '  docker not found yet - reboot and run this script once more.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Done. If WSL was just installed, reboot, then start Docker Desktop.' -ForegroundColor Green
Write-Host 'After reboot, from the project folder:' -ForegroundColor Gray
Write-Host '  docker compose -f deploy/docker-compose.yml up --build' -ForegroundColor Gray
Write-Host '  then open http://localhost:8080' -ForegroundColor Gray
Read-Host 'Press Enter to close'
