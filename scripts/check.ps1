<#
.SYNOPSIS
  Run every check. This is the gate: it must be green before a commit.

.DESCRIPTION
  Backend:  ruff (lint and format check), mypy (strict), pytest (real PostgreSQL arms_test),
            pip-audit (requirements-dev.lock).
  Frontend: eslint, tsc, vitest, npm audit.

  Every step runs even if an earlier one fails, then a summary is printed.
  Exits 1 if any step failed. pip-audit and npm audit need internet access.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $root '.venv\Scripts'
$python = Join-Path $venv 'python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'The Python venv is missing. Run .\scripts\setup.ps1 first.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'frontend\node_modules is missing. Run .\scripts\setup.ps1 first.' -ForegroundColor Red
    exit 1
}

$script:results = New-Object System.Collections.Generic.List[object]

function Invoke-Step {
    param([string]$Name, [string]$Directory, [scriptblock]$Command)
    Write-Host ''
    Write-Host "==> $Name" -ForegroundColor Cyan
    $started = Get-Date
    $global:LASTEXITCODE = 0
    $ok = $false
    Push-Location $Directory
    try {
        & $Command
        $ok = ($LASTEXITCODE -eq 0)
    }
    catch {
        Write-Host $_ -ForegroundColor Red
        $ok = $false
    }
    finally {
        Pop-Location
    }
    $seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    $script:results.Add([pscustomobject]@{
            Step    = $Name
            Result  = $(if ($ok) { 'PASS' } else { 'FAIL' })
            Seconds = $seconds
        })
}

# --- Backend --------------------------------------------------------------------------------
Invoke-Step 'ruff (lint)' $backend { & (Join-Path $venv 'ruff.exe') check . }
Invoke-Step 'ruff (format check)' $backend { & (Join-Path $venv 'ruff.exe') format --check . }
Invoke-Step 'mypy (strict)' $backend { & (Join-Path $venv 'mypy.exe') }
Invoke-Step 'pytest' $backend { & $python -m pytest -q }
Invoke-Step 'pip-audit' $backend {
    & (Join-Path $venv 'pip-audit.exe') -r requirements-dev.lock --progress-spinner off
}

# --- Frontend -------------------------------------------------------------------------------
Invoke-Step 'eslint' $frontend { & npm.cmd run -s lint }
Invoke-Step 'tsc' $frontend { & npm.cmd run -s typecheck }
Invoke-Step 'vitest' $frontend { & npm.cmd run -s test }
Invoke-Step 'npm audit' $frontend { & npm.cmd audit }

# --- Summary --------------------------------------------------------------------------------
Write-Host ''
Write-Host '==================== check.ps1 summary ====================' -ForegroundColor Cyan
foreach ($r in $script:results) {
    $colour = if ($r.Result -eq 'PASS') { 'Green' } else { 'Red' }
    Write-Host ('{0,-22} {1,-5} {2,7}s' -f $r.Step, $r.Result, $r.Seconds) -ForegroundColor $colour
}
$failed = @($script:results | Where-Object { $_.Result -eq 'FAIL' })
if ($failed.Count -gt 0) {
    Write-Host "$($failed.Count) step(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
