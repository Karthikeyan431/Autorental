<#
.SYNOPSIS
  One-time setup from a fresh clone (safe to run again).

.DESCRIPTION
  1. Checks Python 3.12, Node and psql.
  2. Creates .venv with Python 3.12 and installs backend\requirements-dev.lock.
  3. Runs npm ci in frontend (exact versions from package-lock.json).
  4. Runs scripts\db-setup.ps1 (roles, databases, backend\.env).
  5. Applies migrations to arms_dev.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $root '.venv'
$python = Join-Path $venvDir 'Scripts\python.exe'

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { throw "$Name was not found. $Hint" }
}

Write-Host '==> Checking tools' -ForegroundColor Cyan
Assert-Command 'py' 'Install Python 3.12 from python.org (it includes the py launcher).'
& py -3.12 --version
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required: install it from python.org.' }
Assert-Command 'node' 'Install Node.js LTS.'
& node --version
Assert-Command 'npm.cmd' 'Install Node.js LTS.'

Write-Host '==> Python venv (.venv, Python 3.12)' -ForegroundColor Cyan
if (-not (Test-Path $python)) {
    & py -3.12 -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the venv.' }
}
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r (Join-Path $root 'backend\requirements-dev.lock')
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Write-Host '==> Frontend packages (npm ci)' -ForegroundColor Cyan
Push-Location (Join-Path $root 'frontend')
try {
    & npm.cmd ci --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
}
finally { Pop-Location }

Write-Host '==> Databases and backend\.env' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'db-setup.ps1')
if ($LASTEXITCODE -ne 0) {
    # Exit 2: the roles exist but this checkout has no backend\.env (see db-setup.ps1 / README).
    throw "db-setup.ps1 stopped (exit $LASTEXITCODE). Follow its message, then run setup.ps1 again."
}

Write-Host '==> Migrations (arms_dev)' -ForegroundColor Cyan
Push-Location (Join-Path $root 'backend')
try {
    & (Join-Path $venvDir 'Scripts\alembic.exe') upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migrations failed.' }
}
finally { Pop-Location }

Write-Host ''
Write-Host 'Setup complete. Next:' -ForegroundColor Green
Write-Host '  .\scripts\seed.ps1    # fake demo data'
Write-Host '  .\scripts\dev.ps1     # start the API and the web app'
Write-Host '  .\scripts\check.ps1   # run every check'
