# Auto Rental Management System (ARMS)

A web app for an auto-rickshaw rental business, used by the owner and up to 10 staff.
Built by CODE & CANVAS, one weekly milestone at a time (see `docs/milestones/`).
Project rules for contributors and Claude Code: `CLAUDE.md`. Every dependency is free and
open source (`docs/dependencies.md`).

## Windows setup from zero

### 1. Install the free tools (once)

| Tool | Check | Install (if missing) |
| --- | --- | --- |
| Git for Windows | `git --version` | `winget install --id Git.Git -e` |
| Python 3.12 | `py -3.12 --version` | `winget install --id Python.Python.3.12 -e` |
| Node.js LTS, 24 or newer | `node --version` | `winget install --id OpenJS.NodeJS.LTS -e` (installs the current LTS) |
| PostgreSQL 17 | `psql --version` | `winget install --id PostgreSQL.PostgreSQL.17 -e` |

Keep the `postgres` password from the PostgreSQL installer. The setup script asks for it
(or reads the `PGPASSWORD` environment variable); it is never stored by the project.
If `psql` is not found, add `C:\Program Files\PostgreSQL\17\bin` to your PATH.

This project uses **Python 3.12** even if a newer Python is the `py` default.

### 2. Get the code and set up

```powershell
git clone <repository-url> E:\Projects\AutoRentalManagementSystem
Set-Location E:\Projects\AutoRentalManagementSystem
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

`setup.ps1` creates `.venv` (Python 3.12), installs the pinned backend and frontend packages,
creates the PostgreSQL roles `app_owner` and `app_user` and the databases `arms_dev` and
`arms_test`, writes `backend\.env` with random development passwords (gitignored, never
printed), and applies the migrations.

**Second checkout on a machine that is already set up:** the roles already exist, so setup
stops (exit 2) instead of changing their passwords. Copy `backend\.env` from the first checkout,
then run `setup.ps1` again. Only use `db-setup.ps1 -RotatePasswords` if you want new passwords
for every checkout.

### 3. Everyday commands

```powershell
.\scripts\dev.ps1        # API on :8000 (own window) + web app on http://127.0.0.1:5173
.\scripts\dev.ps1 -Lan   # phone testing on your home Wi-Fi (development only; see below)
.\scripts\check.ps1      # the gate: ruff, mypy, pytest, pip-audit, eslint, tsc, vitest, npm audit
.\scripts\seed.ps1       # fake demo data into arms_dev (refuses APP_ENV=production)
.\scripts\create-owner.ps1   # first run: create the owner account (prompts; no default password)
.\scripts\reset-password.ps1  # account recovery (forgotten password or lockout); see docs/handover.md
.\scripts\db-setup.ps1   # roles, databases, backend\.env; never changes existing role passwords
.\scripts\db-setup.ps1 -DryRun           # show what it would do, change nothing
.\scripts\db-setup.ps1 -RotatePasswords  # new role passwords (every checkout must update its .env)
cd backend; ..\.venv\Scripts\alembic upgrade head   # apply migrations by hand
```

If PowerShell blocks scripts, run them as
`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\<name>.ps1`.

### 4. Try it

- Create the owner: `.\scripts\create-owner.ps1`, then sign in at http://127.0.0.1:5173 and set
  up your authenticator app (TOTP) when asked. Save the recovery codes.
- Or, for fake demo users, put a password of your own in `backend\.env` as `SEED_DEV_PASSWORD=`
  and run `.\scripts\seed.ps1`: it adds Test Owner (DEMO) `9000000001` and two staff,
  `9000000002` and `9000000003`, all with that password (only if no owner exists yet).
- Web app: http://127.0.0.1:5173 (resize to phone width; staff mostly use phones).
- Health: http://127.0.0.1:8000/api/v1/health returns `{"status":"ok","db":"ok",...}`.
- API docs (development only): http://127.0.0.1:8000/api/v1/docs
- Demo drivers: with `SEED_DEV_PASSWORD` set, `.\scripts\seed.ps1` also adds Test Driver 001-005
  (DEMO) in different KYC states. If it asks for `LOOKUP_HMAC_KEY`, run `.\scripts\db-setup.ps1`
  once: it adds that key to an existing `backend\.env` without changing anything else.
- Licence expiry job (by hand): `cd backend; ..\.venv\Scripts\python -m app.jobs.run_all`.

#### Phone testing over Wi-Fi (development only)

1. Make your Wi-Fi a **Private** network (Settings > Network & internet > Wi-Fi > your network >
   Private). Check with `Get-NetConnectionProfile`.
2. Allow port 5173 on Private networks only, once, in an **Administrator** PowerShell:
   `New-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)' -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow -Profile Private`
3. Run `.\scripts\dev.ps1 -Lan` and open the printed **`https://<your-pc-ip>:5173`** on the
   phone (note **https**). Vite serves HTTPS with a self-signed certificate made on this PC, so
   the phone gets a secure context: sign-in cookies, "Take photo", the live camera and Web
   Locks all work. The first time, the phone warns that the connection is not private; accept
   it once (`docs/handover.md`, "Phone testing over Wi-Fi"). Opening `http://` instead shows an
   "Open this app over HTTPS" banner.
4. When you are done, remove the rule (Administrator PowerShell):
   `Remove-NetFirewallRule -DisplayName 'ARMS dev (Vite 5173, Private)'`

### 5. Continuous integration

`.github/workflows/checks.yml` runs the same checks as `check.ps1` on GitHub (Ubuntu, PostgreSQL
17 service container) for pushes to `master` and for pull requests. It uses only secrets
generated during the run. The `db-setup.ps1` tests are Windows-only and are skipped there.

## Layout

```
backend/    FastAPI app (app/), Alembic migrations (alembic/), tests (tests/)
frontend/   React + TypeScript + Vite app (src/)
scripts/    setup, db-setup, dev, check, seed (PowerShell)
deploy/     Caddyfile and systemd templates (used from Week 8)
docs/       requirements, business rules, data model, milestones, decisions
```

## Rules that never bend

Two roles only (owner and staff), money in integer paise, never a full Aadhaar number, no real
personal data in code or tests, no mock verification in production, no secrets in source, and
no paid services. Details in `CLAUDE.md`.
