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

### 3. Everyday commands

```powershell
.\scripts\dev.ps1        # API on :8000 (own window) + web app on http://127.0.0.1:5173
.\scripts\check.ps1      # the gate: ruff, mypy, pytest, pip-audit, eslint, tsc, vitest, npm audit
.\scripts\seed.ps1       # fake demo data into arms_dev (refuses APP_ENV=production)
.\scripts\db-setup.ps1   # re-create roles/databases/backend\.env (keeps existing passwords)
cd backend; ..\.venv\Scripts\alembic upgrade head   # apply migrations by hand
```

If PowerShell blocks scripts, run them as
`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\<name>.ps1`.

### 4. Try it

- Web app: http://127.0.0.1:5173 (click through the empty pages; resize to phone width).
- Health: http://127.0.0.1:8000/api/v1/health returns `{"status":"ok","db":"ok",...}`.
- API docs (development only): http://127.0.0.1:8000/api/v1/docs

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
