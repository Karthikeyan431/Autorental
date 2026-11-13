<#
.SYNOPSIS
  One-time local database setup for ARMS (safe to run again).

.DESCRIPTION
  Connects to the local PostgreSQL server as the superuser (default: postgres) and makes sure
  these exist: the roles app_owner (owns the schema, runs migrations) and app_user (runtime),
  the databases arms_dev and arms_test, and backend\.env.

  Existing role passwords are NEVER changed unless you pass -RotatePasswords:
    * Roles missing          -> created with new random passwords; backend\.env written.
    * Roles exist, .env here -> nothing about passwords changes; .env is kept as it is.
    * Roles exist, no .env   -> refused (exit 2). This is a second checkout on a machine that is
                                already set up: copy backend\.env from the first checkout, or
                                re-run with -RotatePasswords (which changes the passwords for
                                every checkout that uses these roles).

  -RotatePasswords sets new random passwords on both roles and rewrites only the four database
  URL lines in backend\.env (other secrets are kept).

  Keys added in later weeks are appended to an existing backend\.env when missing, and never
  replaced once set: LOOKUP_HMAC_KEY (Week 3, licence-number duplicate checks; changing it would
  break those checks, so back it up with the other keys).
  -DryRun prints the plan and changes nothing (no roles, databases, passwords or files).

  The superuser password comes from PGPASSWORD, or psql prompts for it. It is never written
  anywhere. Generated passwords are never printed.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\db-setup.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\db-setup.ps1 -DryRun
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\db-setup.ps1 -RotatePasswords
#>
[CmdletBinding()]
param(
    [string]$PgHost = 'localhost',
    [int]$PgPort = 5432,
    [string]$PgSuperUser = 'postgres',
    [switch]$RotatePasswords,
    [switch]$DryRun,
    # Defaults to backend\.env. Tests point this at a temporary file.
    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$EXIT_REFUSED = 2
$root = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) { $EnvFile = Join-Path $root 'backend\.env' }
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

function Write-Plan([string]$Text) { Write-Host "PLAN: $Text" }

# --- Safety: an env file inside the repo must be gitignored before we create it ---------------
$rootFull = [System.IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
if ($EnvFile.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    $relative = $EnvFile.Substring($rootFull.Length).Replace('\', '/')
    Push-Location $root
    try {
        & git check-ignore -q -- $relative
        if ($LASTEXITCODE -ne 0) { throw "$relative is not ignored by git. Fix .gitignore first." }
    }
    finally { Pop-Location }
}

# --- Find psql ---------------------------------------------------------------------------------
$psqlCommand = Get-Command psql -ErrorAction SilentlyContinue
if ($psqlCommand) { $psqlPath = $psqlCommand.Source }
else {
    $psqlPath = 'C:\Program Files\PostgreSQL\17\bin\psql.exe'
    if (-not (Test-Path $psqlPath)) { throw 'psql was not found. Install PostgreSQL 17 or add its bin folder to PATH.' }
}
$psqlArgs = @('-X', '-q', '-h', $PgHost, '-p', $PgPort, '-U', $PgSuperUser, '-d', 'postgres')

# --- Random values -----------------------------------------------------------------------------
function New-RandomBytes([int]$Count) {
    $bytes = New-Object byte[] $Count
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return , $bytes
}
function New-HexSecret([int]$Bytes) { return -join ((New-RandomBytes $Bytes) | ForEach-Object { '{0:x2}' -f $_ }) }
function New-Base64Key { return [Convert]::ToBase64String((New-RandomBytes 32)) }

function Get-DatabaseUrls([string]$OwnerPw, [string]$UserPw) {
    $hostPort = "${PgHost}:$PgPort"
    return [ordered]@{
        'DATABASE_URL'                = "postgresql+psycopg://app_user:$UserPw@$hostPort/arms_dev"
        'MIGRATION_DATABASE_URL'      = "postgresql+psycopg://app_owner:$OwnerPw@$hostPort/arms_dev"
        'TEST_DATABASE_URL'           = "postgresql+psycopg://app_user:$UserPw@$hostPort/arms_test"
        'TEST_MIGRATION_DATABASE_URL' = "postgresql+psycopg://app_owner:$OwnerPw@$hostPort/arms_test"
    }
}

function Get-EnvPassword([string]$Role) {
    if (-not (Test-Path $EnvFile)) { return $null }
    $content = Get-Content -Raw -Path $EnvFile
    $key = if ($Role -eq 'app_owner') { 'MIGRATION_DATABASE_URL' } else { 'DATABASE_URL' }
    $m = [regex]::Match($content, "(?m)^$key=postgresql\+psycopg://${Role}:([0-9a-f]+)@")
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

# --- Read the current state (read-only) ----------------------------------------------------------
$existing = & $psqlPath @psqlArgs -t -A -v ON_ERROR_STOP=1 -c "SELECT rolname FROM pg_roles WHERE rolname IN ('app_owner', 'app_user') ORDER BY 1"
if ($LASTEXITCODE -ne 0) { throw "Could not connect to PostgreSQL as $PgSuperUser (psql exit $LASTEXITCODE)." }
$existing = @($existing | Where-Object { $_ })
$ownerExists = $existing -contains 'app_owner'
$userExists = $existing -contains 'app_user'
$envExists = Test-Path $EnvFile

# --- Decide ----------------------------------------------------------------------------------
# $passwords[role] = new password to set, or $null to leave the role's password alone.
$passwords = @{ 'app_owner' = $null; 'app_user' = $null }
$envAction = 'keep'   # keep | write | rewrite-urls

if ($RotatePasswords) {
    $passwords['app_owner'] = New-HexSecret 24
    $passwords['app_user'] = New-HexSecret 24
    $envAction = if ($envExists) { 'rewrite-urls' } else { 'write' }
    Write-Plan 'rotate the passwords of app_owner and app_user (every checkout using them must update its .env)'
}
else {
    foreach ($role in 'app_owner', 'app_user') {
        $exists = if ($role -eq 'app_owner') { $ownerExists } else { $userExists }
        if ($exists) {
            Write-Plan "keep role $role and its existing password"
            continue
        }
        # A missing role: reuse the password from an existing .env, or generate one.
        $fromEnv = Get-EnvPassword $role
        if ($fromEnv) { $passwords[$role] = $fromEnv; Write-Plan "create role $role with the password already in the env file" }
        else { $passwords[$role] = New-HexSecret 24; Write-Plan "create role $role with a new random password" }
    }

    if (-not $envExists) {
        if ($ownerExists -or $userExists) {
            Write-Host ''
            Write-Host "REFUSED: the roles already exist, but $EnvFile does not." -ForegroundColor Yellow
            Write-Host 'Their passwords cannot be recovered, and they will not be changed silently.'
            Write-Host 'Either copy backend\.env from the checkout that created the roles, or re-run with'
            Write-Host '-RotatePasswords (this changes the passwords for every checkout that uses these roles).'
            exit $EXIT_REFUSED
        }
        $envAction = 'write'
    }
    elseif ((-not $ownerExists -and -not (Get-EnvPassword 'app_owner')) -or (-not $userExists -and -not (Get-EnvPassword 'app_user'))) {
        # Roles were (re)created with new passwords that the existing .env does not hold.
        $envAction = 'rewrite-urls'
    }
}
switch ($envAction) {
    'keep' { Write-Plan "keep $EnvFile unchanged" }
    'write' { Write-Plan "write $EnvFile with the database URLs and new development keys" }
    'rewrite-urls' { Write-Plan "update only the four database URL lines in $EnvFile" }
}
Write-Plan 'make sure databases arms_dev and arms_test exist, owned by app_owner'

# Keys introduced after Week 1: added when missing, never replaced (their values are never shown).
$missingKeys = @()
if ($envExists -and $envAction -ne 'write') {
    $currentEnv = Get-Content -Raw -Path $EnvFile
    if ($currentEnv -notmatch '(?m)^LOOKUP_HMAC_KEY=\S') { $missingKeys += 'LOOKUP_HMAC_KEY' }
    $currentEnv = $null
}
foreach ($key in $missingKeys) { Write-Plan "add a new $key to $EnvFile (existing values are never replaced)" }

if ($DryRun) {
    Write-Host 'Dry run: nothing was changed.'
    exit 0
}

# --- Apply: roles and databases (SQL on stdin, so passwords never appear on a command line) ---
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('\set ON_ERROR_STOP on')
foreach ($role in 'app_owner', 'app_user') {
    $lines.Add("SELECT 'CREATE ROLE $role LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role') \gexec")
    # Attributes only; this never touches the password.
    $lines.Add("ALTER ROLE $role WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;")
    if ($passwords[$role]) {
        $lines.Add("\set pw '$($passwords[$role])'")
        $lines.Add("ALTER ROLE $role WITH PASSWORD :'pw';")
    }
}
foreach ($db in 'arms_dev', 'arms_test') {
    $lines.Add("SELECT 'CREATE DATABASE $db OWNER app_owner ENCODING ''UTF8'' TEMPLATE template0' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$db') \gexec")
    $lines.Add("REVOKE ALL ON DATABASE $db FROM PUBLIC;")
    $lines.Add("GRANT CONNECT, TEMPORARY ON DATABASE $db TO app_user;")
}
($lines -join "`n") | & $psqlPath @psqlArgs
if ($LASTEXITCODE -ne 0) { throw "psql failed (exit $LASTEXITCODE)." }
$lines = $null

# --- Apply: the env file -----------------------------------------------------------------------
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$ownerPw = if ($passwords['app_owner']) { $passwords['app_owner'] } else { Get-EnvPassword 'app_owner' }
$userPw = if ($passwords['app_user']) { $passwords['app_user'] } else { Get-EnvPassword 'app_user' }

if ($envAction -eq 'write') {
    $urls = Get-DatabaseUrls $ownerPw $userPw
    $out = @(
        "# Local development settings, written by scripts\db-setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd').",
        '# NEVER commit this file. backend/.env.example documents every variable.',
        'APP_ENV=development'
    )
    foreach ($k in $urls.Keys) { $out += "$k=$($urls[$k])" }
    $out += @(
        "SECRET_KEY=$(New-HexSecret 32)",
        "FIELD_ENCRYPTION_KEY=$(New-Base64Key)",
        "FILE_ENCRYPTION_KEYS=dev1:$(New-Base64Key)",
        'ACTIVE_FILE_KEY_ID=dev1',
        "LOOKUP_HMAC_KEY=$(New-Base64Key)",
        'LOG_LEVEL=INFO',
        'AADHAAR_QR_INAPP_ENABLED=false',
        'DEMO_VERIFIER_ENABLED=false'
    )
    [System.IO.File]::WriteAllText($EnvFile, (($out -join "`n") + "`n"), $utf8NoBom)
    Write-Host "Wrote $EnvFile (values not shown)."
}
elseif ($envAction -eq 'rewrite-urls') {
    $urls = Get-DatabaseUrls $ownerPw $userPw
    $kept = @(Get-Content -Path $EnvFile | Where-Object { $_ -notmatch '^(TEST_)?(MIGRATION_)?DATABASE_URL=' })
    foreach ($k in $urls.Keys) { $kept += "$k=$($urls[$k])" }
    [System.IO.File]::WriteAllText($EnvFile, (($kept -join "`n") + "`n"), $utf8NoBom)
    Write-Host "Updated the database URLs in $EnvFile (values not shown)."
}
else {
    Write-Host "Kept $EnvFile unchanged."
}
if ($missingKeys.Count -gt 0) {
    $existingEnv = [System.IO.File]::ReadAllText($EnvFile)
    $sep = if ($existingEnv.EndsWith("`n")) { '' } else { "`n" }
    $added = @()
    foreach ($key in $missingKeys) {
        if ($key -eq 'LOOKUP_HMAC_KEY') {
            $added += '# Week 3: licence-number duplicate checks. Never change it; back it up with the other keys.'
            $added += "LOOKUP_HMAC_KEY=$(New-Base64Key)"
        }
    }
    [System.IO.File]::WriteAllText($EnvFile, $existingEnv + $sep + (($added -join "`n") + "`n"), $utf8NoBom)
    $existingEnv = $null; $added = $null
    Write-Host "Added $($missingKeys -join ', ') to $EnvFile (values not shown)."
}
$passwords = $null; $ownerPw = $null; $userPw = $null

Write-Host 'Roles app_owner and app_user are ready.'
Write-Host 'Databases arms_dev and arms_test are ready (owned by app_owner).'
