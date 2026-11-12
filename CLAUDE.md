# Auto Rental Management System — project guide for Claude Code

Agency: CODE & CANVAS. Client: [Client name], an auto-rickshaw rental business in India.
Plan version: v2, 12 November 2026 (after the client meeting, zero-cost version).

## What we are building

A responsive web app used only by the **owner** and up to **10 staff**. Drivers do not log in.

- Staff register drivers, take their photo, record consent, verify identity and licence, and manage them.
- Every driver record shows **who created it** and **which staff member manages it**.
- Autos, rental agreements and a **daily rent ledger** (one charge per calendar day).
- Rent is collected through **daily UPI pay requests** that staff send on WhatsApp with one tap. There is no automatic debit.
- **Every payment counts only after the owner approves it.** The owner uploads the bank statement, and the system matches payments for one-click approval.
- When a driver misses rent, the owner **escalates** to the managing staff member, and the follow-up is tracked until it is cleared.
- The owner sees everything: the dashboard, reports, Excel export and the audit log.

## Hard constraints: never break these without written approval

1. **Zero running cost.** No paid service, API or SaaS of any kind. Use only free, open-source libraries, free government services (UIDAI Secure QR, the Parivahan portal) and free hosting (Oracle Cloud Always Free). If a task seems to need anything paid, stop and ask.
2. **Two roles only: owner and staff.** No driver accounts, no driver app, no `/me` endpoints.
3. **Business rules** in `docs/business-rules.md` are enforced in the backend, with database constraints wherever possible, and every rule has tests.
4. **Money is integer paise** (`BIGINT`). Never use floats for money. Format rupees only in the UI.
5. **Never store a full Aadhaar number.** Keep the last 4 digits only. Never log personal data such as names, mobiles, Aadhaar, licence numbers or addresses.
6. **Never claim a check succeeded unless it really did.** Any demo or mock verifier must be impossible to enable when `APP_ENV=production`; the app refuses to start.
7. **No real personal data** in code, tests, seeds or fixtures. Use obviously fake data, such as names like "Test Driver 001" and mobile numbers starting with `90000`.
8. **No secrets in source.** All config comes from the environment. Keep `.env.example` current.
9. **Do not invent requirements.** Open questions use the defaults in `docs/open-questions.md`. Implement them as settings or flags where practical. If something is not covered, ask.

## Stack

- **Backend:** Python 3.12 (create the venv with `py -3.12 -m venv .venv`; this laptop also has Python 3.14 as the `py` default, which we do not use), FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.0, Alembic, psycopg 3 (binary), uvicorn, PostgreSQL 17. Libraries: argon2-cffi, PyJWT, pyotp, cryptography, Pillow, openpyxl, reportlab, qrcode, pywebpush, python-multipart, APScheduler (development scheduling only; production uses the systemd timer). Tests: pytest, httpx. Lint, types and audit: ruff, mypy, pip-audit.
- **Frontend:** React and TypeScript with Vite, Tailwind CSS, React Router, TanStack Query, react-hook-form with zod, and @zxing/browser for QR scanning. Tests: Vitest and Testing Library. Lint and format: ESLint, Prettier. Playwright for a few end-to-end flows in Week 8.
- **Versions:** use current stable releases of each, and pin them (lock files committed). Every dependency must be free and open source. `docs/dependencies.md` lists each package with its version and licence; update it whenever a dependency is added or upgraded.
- **Development:** Windows with PowerShell. Tests run against a real PostgreSQL test database, never SQLite, because the constraints matter.
- **Production:** Ubuntu on Oracle Cloud Always Free (Arm64), Caddy for HTTPS (Let's Encrypt), systemd services, and a free subdomain. See `docs/deployment.md`.

## Repository layout

```
backend/
  app/main.py
  app/core/            config, db, security, money, time, errors, audit, files
  app/modules/<name>/  models.py, schemas.py, service.py, router.py
  app/jobs/            idempotent CLI jobs (rent accrual, pay requests, alerts)
  alembic/
  tests/
frontend/
  src/app/ src/features/<name>/ src/components/ src/lib/
deploy/      Caddyfile, systemd units, backup scripts
scripts/     check.ps1, dev.ps1, seed.ps1
docs/        requirements, rules, data model, milestones
```

## How we work, every session

- Work **one milestone at a time** from `docs/milestones/`. Start one with `/milestone 01` (or 02, 03 and so on).
- For each milestone:
  1. Read the brief and the docs it lists.
  2. Propose a plan: files, migrations, endpoints, screens, and the tests to write first. Then **wait for approval**.
  3. Write the business-rule tests first.
  4. Implement.
  5. Run `.\scripts\check.ps1` until it is green.
  6. Summarise what was built, how to try it, what is left, and any decision you need.
- Business logic lives in `service.py`, never in routers or the UI.
- Every write endpoint has a permission check, validation, one database transaction and an audit entry.
- Every schema change is an Alembic migration. Never edit a migration that has already been applied. An insert-only table gets `make_insert_only_sql()` in its migration and an entry in `INSERT_ONLY_TABLES` (see `docs/data-model.md`).
- Audit entries are written with `write_audit()` in the same transaction as the change; never commit them separately.
- Register every new models module in `backend/app/models.py`.
- Fix the cause when a test fails. Never weaken, skip or delete a test to make it pass.
- Ask before deleting files, changing a business rule, adding a dependency that is not listed above, or changing the plan.
- Commit in small steps once the checks pass, with clear messages.

## Commands (PowerShell; Week 1 creates them, so keep this list accurate)

```powershell
.\scripts\setup.ps1      # one-time from a fresh clone: .venv (3.12), packages, db-setup, migrations
.\scripts\db-setup.ps1   # roles app_owner/app_user, databases arms_dev/arms_test, backend\.env (never prints passwords)
.\scripts\dev.ps1        # migrations, then API (uvicorn --reload, :8000, own window) and Vite (:5173, proxies /api)
.\scripts\check.ps1      # the gate: ruff, mypy, pytest, pip-audit, eslint, tsc, vitest, npm audit
.\scripts\seed.ps1       # load fake demo data into the dev database (refuses APP_ENV=production)
cd backend; ..\.venv\Scripts\alembic upgrade head
```

From Claude Code's shell, run a script as `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1`.
The venv lives at the repo root (`.venv`). Tests rebuild the `arms_test` schema on every run.

## Time and money

- Business time zone: `Asia/Kolkata`. Store timestamps as `timestamptz` in UTC. Rent dates are local calendar dates.
- Money is integer paise everywhere. ₹300 is `30000`. Show rupees with Indian digit grouping (₹1,20,000); whole amounts show no `.00`, and paise appear only when non-zero (₹1,20,000.50). Right-align money in tables. Excel exports keep real numbers with a 2-decimal rupee format.

## Reference docs (read the ones a milestone lists)

- `docs/requirements.md`: scope, roles, screens, what is out of scope
- `docs/business-rules.md`: the 18 rules and how each is enforced and tested
- `docs/data-model.md`: tables, columns and constraints
- `docs/rent-and-payments.md`: rent engine, pay requests, statement matching, approvals, allocation, escalations
- `docs/kyc.md`: consent, UIDAI Secure QR, Parivahan lookup, manual review, documents
- `docs/api.md`: endpoint modules and the error format
- `docs/security.md`: authentication, permissions, files, audit, backups
- `docs/open-questions.md`: open client questions and the defaults to build
- `docs/deployment.md`: free hosting on Oracle Cloud
- `docs/dependencies.md`: every package, its pinned version and licence
- `docs/decisions.md`: decisions made with the agency lead, with dates
- `docs/milestones/week-01.md` to `week-08.md`

## Glossary

- **Driver:** a person who rents an auto. Not a user of the app.
- **Auto / vehicle:** an auto-rickshaw.
- **Agreement:** one driver renting one auto from a start date.
- **Rent charge:** one row per agreement per calendar day.
- **Allocation:** money from an approved payment applied to a specific day.
- **Pay request:** a UPI link and QR for the amount due, sent on WhatsApp by staff.
- **Statement line:** one credit row from the owner's uploaded bank statement.
- **Approval:** the owner's decision that a payment counts.
- **Escalation:** the owner asking the managing staff member to follow up a missed payment.
- **Created by / Managed by:** the staff member who registered the driver, and the one responsible for them now.
