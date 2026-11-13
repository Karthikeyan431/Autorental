<#
.SYNOPSIS
  First-run command: create the single owner account (prompts in the terminal).

.DESCRIPTION
  Runs `python -m app.cli.create_owner` against the database in backend\.env.
  Asks for the owner's name, mobile, optional email and a password (typed twice, hidden).
  There is no default password. Refuses if an owner already exists.
  The owner sets up their authenticator app (TOTP) at the first sign-in in the browser.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-owner.ps1
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
    & $python -m app.cli.create_owner
    $code = $LASTEXITCODE
}
finally { Pop-Location }
exit $code
