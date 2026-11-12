<#
.SYNOPSIS
  Load obviously fake demo data into the development database (arms_dev).

.DESCRIPTION
  Runs `python -m app.cli.seed`. Safe to run more than once. Refuses to run when
  APP_ENV=production. Week 1 seeds only the first settings version; later weeks add staff,
  drivers and autos.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\seed.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'The Python venv is missing. Run .\scripts\setup.ps1 first.' }

Push-Location (Join-Path $root 'backend')
try {
    & $python -m app.cli.seed
    $code = $LASTEXITCODE
}
finally { Pop-Location }
exit $code
