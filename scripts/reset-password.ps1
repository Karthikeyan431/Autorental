<#
.SYNOPSIS
  Account recovery: set a new password for a user (prompts in the terminal).

.DESCRIPTION
  Runs `python -m app.cli.reset_password` against the database in backend\.env.
  Asks which user (mobile number or email), then the new password twice (hidden, normal
  password policy). It clears the lockout, signs the user out everywhere and forces a password
  change at the next sign-in. The audit entry's actor is "system:cli".

  -ResetTotp also clears the owner's 2-step sign-in, so the next sign-in sets up a new
  authenticator app (use it when the phone with the authenticator is lost).

  Works in every environment, including production: it needs shell access to the server.
  See docs/handover.md, "Owner account recovery".

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\reset-password.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\reset-password.ps1 -ResetTotp
#>
[CmdletBinding()]
param(
    # Also clear the owner's 2-step sign-in (authenticator app) setup.
    [switch]$ResetTotp
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'The Python venv is missing. Run .\scripts\setup.ps1 first.' }

$cliArgs = @('-m', 'app.cli.reset_password')
if ($ResetTotp) { $cliArgs += '--reset-totp' }

Push-Location (Join-Path $root 'backend')
try {
    & $python @cliArgs
    $code = $LASTEXITCODE
}
finally { Pop-Location }
exit $code
