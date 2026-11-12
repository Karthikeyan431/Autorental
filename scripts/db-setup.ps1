<#
.SYNOPSIS
  One-time local database setup for ARMS (safe to run again).

.DESCRIPTION
  Connects to the local PostgreSQL server as the superuser (default: postgres) and:
    1. creates the roles app_owner (owns the schema, runs migrations) and app_user (runtime);
    2. creates the databases arms_dev and arms_test, owned by app_owner;
    3. writes backend\.env with random development passwords and dev-only secrets.

  The superuser password comes from the PGPASSWORD environment variable, or psql prompts for it.
  It is never written anywhere. The generated passwords are never printed.

  If backend\.env already exists, its passwords are kept and re-applied to the roles, so the file
  and the database stay in sync. Use -ResetPasswords to generate new ones.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\db-setup.ps1
#>
[CmdletBinding()]
param(
    [string]$PgHost = 'localhost',
    [int]$PgPort = 5432,
    [string]$PgSuperUser = 'postgres',
    [switch]$ResetPasswords
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root 'backend\.env'

# --- Safety: backend\.env must be gitignored before we create it -------------------------------
Push-Location $root
try {
    & git check-ignore -q -- 'backend/.env'
    if ($LASTEXITCODE -ne 0) {
        throw 'backend/.env is not ignored by git. Fix .gitignore before running this script.'
    }
}
finally {
    Pop-Location
}

# --- Find psql ---------------------------------------------------------------------------------
$psql = (Get-Command psql -ErrorAction SilentlyContinue)
if ($psql) {
    $psqlPath = $psql.Source
}
else {
    $psqlPath = 'C:\Program Files\PostgreSQL\17\bin\psql.exe'
    if (-not (Test-Path $psqlPath)) {
        throw 'psql was not found. Install PostgreSQL 17 or add its bin folder to PATH.'
    }
}

# --- Random values -----------------------------------------------------------------------------
function New-RandomBytes([int]$Count) {
    $bytes = New-Object byte[] $Count
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return , $bytes
}
function New-HexSecret([int]$Bytes) {
    return -join ((New-RandomBytes $Bytes) | ForEach-Object { '{0:x2}' -f $_ })
}
function New-Base64Key {
    return [Convert]::ToBase64String((New-RandomBytes 32))
}

# --- Passwords: reuse from an existing .env, or generate ----------------------------------------
$ownerPw = $null
$userPw = $null
$writeEnv = $true
if ((Test-Path $envFile) -and -not $ResetPasswords) {
    $content = Get-Content -Raw -Path $envFile
    $mOwner = [regex]::Match($content, '(?m)^MIGRATION_DATABASE_URL=postgresql\+psycopg://app_owner:([0-9a-f]+)@')
    $mUser = [regex]::Match($content, '(?m)^DATABASE_URL=postgresql\+psycopg://app_user:([0-9a-f]+)@')
    if (-not ($mOwner.Success -and $mUser.Success)) {
        throw 'backend\.env exists but its database URLs were not recognised. Re-run with -ResetPasswords.'
    }
    $ownerPw = $mOwner.Groups[1].Value
    $userPw = $mUser.Groups[1].Value
    $writeEnv = $false
}
else {
    $ownerPw = New-HexSecret 24
    $userPw = New-HexSecret 24
}

# --- Roles and databases (SQL goes to psql on stdin, so passwords never appear on a command line) -
$sql = @"
\set ON_ERROR_STOP on
\set owner_pw '$ownerPw'
\set user_pw '$userPw'
SELECT 'CREATE ROLE app_owner LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_owner') \gexec
SELECT 'CREATE ROLE app_user LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') \gexec
ALTER ROLE app_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'owner_pw';
ALTER ROLE app_user WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'user_pw';
SELECT 'CREATE DATABASE arms_dev OWNER app_owner ENCODING ''UTF8'' TEMPLATE template0' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'arms_dev') \gexec
SELECT 'CREATE DATABASE arms_test OWNER app_owner ENCODING ''UTF8'' TEMPLATE template0' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'arms_test') \gexec
REVOKE ALL ON DATABASE arms_dev FROM PUBLIC;
REVOKE ALL ON DATABASE arms_test FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE arms_dev TO app_user;
GRANT CONNECT, TEMPORARY ON DATABASE arms_test TO app_user;
"@

$sql | & $psqlPath -X -q -h $PgHost -p $PgPort -U $PgSuperUser -d postgres
if ($LASTEXITCODE -ne 0) {
    throw "psql failed (exit $LASTEXITCODE). Check that PostgreSQL is running and the $PgSuperUser password is correct."
}
$sql = $null

# --- backend\.env ------------------------------------------------------------------------------
if ($writeEnv) {
    $hostPort = "${PgHost}:$PgPort"
    $today = Get-Date -Format 'yyyy-MM-dd'
    $lines = @(
        "# Local development settings, written by scripts\db-setup.ps1 on $today.",
        '# NEVER commit this file. backend/.env.example documents every variable.',
        'APP_ENV=development',
        "DATABASE_URL=postgresql+psycopg://app_user:$userPw@$hostPort/arms_dev",
        "MIGRATION_DATABASE_URL=postgresql+psycopg://app_owner:$ownerPw@$hostPort/arms_dev",
        "TEST_DATABASE_URL=postgresql+psycopg://app_user:$userPw@$hostPort/arms_test",
        "TEST_MIGRATION_DATABASE_URL=postgresql+psycopg://app_owner:$ownerPw@$hostPort/arms_test",
        "SECRET_KEY=$(New-HexSecret 32)",
        "FIELD_ENCRYPTION_KEY=$(New-Base64Key)",
        "FILE_ENCRYPTION_KEYS=dev1:$(New-Base64Key)",
        'ACTIVE_FILE_KEY_ID=dev1',
        'CORS_ORIGIN=http://localhost:5173',
        'LOG_LEVEL=INFO',
        'AADHAAR_QR_INAPP_ENABLED=false',
        'DEMO_VERIFIER_ENABLED=false'
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($envFile, (($lines -join "`n") + "`n"), $utf8NoBom)
    Write-Host 'backend\.env written with new random development passwords and keys (values not shown).'
}
else {
    Write-Host 'backend\.env already exists: kept its passwords and re-applied them to the roles.'
}
$ownerPw = $null
$userPw = $null

Write-Host 'Roles app_owner and app_user are ready.'
Write-Host 'Databases arms_dev and arms_test are ready (owned by app_owner).'
Write-Host 'Next: run migrations with  cd backend; ..\.venv\Scripts\alembic upgrade head'
