<#
.SYNOPSIS
  Start the backend and frontend for development.

.DESCRIPTION
  1. Applies migrations to arms_dev (alembic upgrade head, as app_owner).
  2. Starts the API (uvicorn --reload) on http://127.0.0.1:8000 in its own window.
  3. Starts Vite on http://127.0.0.1:5173 in this window. Vite forwards /api to the API,
     so the browser sees one origin, as it will behind Caddy in production.
  Press Ctrl+C to stop Vite; the API window is closed too.

  -Lan (development only): phone testing over the home Wi-Fi. Vite listens on this PC's LAN
  address with HTTPS (a self-signed certificate made on this PC by @vitejs/plugin-basic-ssl,
  kept under frontend\node_modules\.vite, never in git) and prints the https:// URL to open on
  the phone. HTTPS gives the phone a secure context, so sign-in cookies (always Secure), the
  live camera and Web Locks all work. The phone warns about the certificate the first time;
  docs/handover.md says how to accept it. The API stays on 127.0.0.1 (Vite forwards /api and
  adds X-Forwarded-For, which uvicorn trusts only from 127.0.0.1).

  Windows Firewall must allow port 5173 on Private networks only. In an Administrator PowerShell:
    New-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)' -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private
  Remove it when you are done:
    Remove-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)'
  Your Wi-Fi must be a Private network (Settings > Network & internet > Wi-Fi > Private), never
  Public. Check with: Get-NetConnectionProfile

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Lan
#>
[CmdletBinding()]
param(
    [switch]$SkipMigrations,
    # Phone testing over the home Wi-Fi (development only; see the description).
    [switch]$Lan
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $root '.venv\Scripts'
$python = Join-Path $venv 'python.exe'

if (-not (Test-Path $python)) { throw 'The Python venv is missing. Run .\scripts\setup.ps1 first.' }
if (-not (Test-Path (Join-Path $backend '.env'))) { throw 'backend\.env is missing. Run .\scripts\db-setup.ps1 first.' }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { throw 'frontend\node_modules is missing. Run .\scripts\setup.ps1 first.' }

$lanIp = $null
if ($Lan) {
    # The IPv4 address of the adapter that has a default gateway (the home Wi-Fi or Ethernet).
    $config = Get-NetIPConfiguration | Where-Object {
        $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address
    } | Select-Object -First 1
    if (-not $config) { throw 'No connected network with a gateway was found. Connect to your Wi-Fi first.' }
    $lanIp = @($config.IPv4Address)[0].IPAddress
    $netProfile = Get-NetConnectionProfile -InterfaceIndex $config.InterfaceIndex -ErrorAction SilentlyContinue
    if ($netProfile -and $netProfile.NetworkCategory -ne 'Private') {
        Write-Host "WARNING: '$($netProfile.Name)' is a $($netProfile.NetworkCategory) network. Use -Lan only on your own Private network." -ForegroundColor Yellow
    }
    $rule = Get-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)' -ErrorAction SilentlyContinue
    if (-not $rule) {
        Write-Host 'The firewall rule for port 5173 is missing. In an Administrator PowerShell run:' -ForegroundColor Yellow
        Write-Host "  New-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)' -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private"
    }
}

if (-not $SkipMigrations) {
    Write-Host '==> alembic upgrade head' -ForegroundColor Cyan
    Push-Location $backend
    try {
        & (Join-Path $venv 'alembic.exe') upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Migrations failed.' }
    }
    finally { Pop-Location }
}

Write-Host '==> API on http://127.0.0.1:8000 (own window)' -ForegroundColor Cyan
# --no-access-log: uvicorn's access log would record client IPs and query strings; the app
# logs one line per request itself (method, path, status, duration, request id).
# --forwarded-allow-ips 127.0.0.1: trust X-Forwarded-For only from the Vite proxy on this PC.
$api = Start-Process -FilePath $python -WorkingDirectory $backend -PassThru -ArgumentList @(
    '-m', 'uvicorn', 'app.main:create_app', '--factory', '--reload',
    '--host', '127.0.0.1', '--port', '8000', '--no-access-log',
    '--forwarded-allow-ips', '127.0.0.1'
)

try {
    Push-Location $frontend
    try {
        if ($Lan) {
            Write-Host "==> Web app for your phone: https://${lanIp}:5173  (same Wi-Fi; Ctrl+C to stop)" -ForegroundColor Green
            Write-Host '    First visit: the phone warns about the certificate. Tap Advanced, then Proceed (docs/handover.md).'
            # Only for this Vite run: HTTPS and X-Forwarded-For (vite.config.ts).
            $previousLan = $env:ARMS_DEV_LAN
            $env:ARMS_DEV_LAN = '1'
            try { & npm.cmd run dev -- --host $lanIp }
            finally { $env:ARMS_DEV_LAN = $previousLan }
        }
        else {
            Write-Host '==> Web app on http://127.0.0.1:5173  (Ctrl+C to stop)' -ForegroundColor Cyan
            & npm.cmd run dev
        }
    }
    finally { Pop-Location }
}
finally {
    if ($api -and -not $api.HasExited) {
        Write-Host '==> Stopping the API' -ForegroundColor Cyan
        # /T also stops the reload worker process uvicorn started.
        & taskkill.exe /PID $api.Id /T /F | Out-Null
    }
}
