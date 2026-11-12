<#
.SYNOPSIS
  Start the backend and frontend for development.

.DESCRIPTION
  1. Applies migrations to arms_dev (alembic upgrade head, as app_owner).
  2. Starts the API (uvicorn --reload) on http://127.0.0.1:8000 in its own window.
  3. Starts Vite on http://127.0.0.1:5173 in this window. Vite forwards /api to the API,
     so the browser sees one origin, as it will behind Caddy in production.
  Press Ctrl+C to stop Vite; the API window is closed too.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipMigrations
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
# --no-access-log: uvicorn's access log would record client IPs and query strings;
# the app logs each request itself without them.
$api = Start-Process -FilePath $python -WorkingDirectory $backend -PassThru -ArgumentList @(
    '-m', 'uvicorn', 'app.main:create_app', '--factory', '--reload',
    '--host', '127.0.0.1', '--port', '8000', '--no-access-log'
)

try {
    Write-Host '==> Web app on http://127.0.0.1:5173  (Ctrl+C to stop)' -ForegroundColor Cyan
    Push-Location $frontend
    try { & npm.cmd run dev }
    finally { Pop-Location }
}
finally {
    if ($api -and -not $api.HasExited) {
        Write-Host '==> Stopping the API' -ForegroundColor Cyan
        # /T also stops the reload worker process uvicorn started.
        & taskkill.exe /PID $api.Id /T /F | Out-Null
    }
}
