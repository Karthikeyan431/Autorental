# Week 1: Discovery, setup and foundations

**Goal:** a clean, runnable project skeleton on Windows, with the database, migrations, money and time utilities, the audit log and the checks script, so every later week builds on solid ground. No business features yet.

**Read first:** `CLAUDE.md`, `docs/requirements.md`, `docs/data-model.md` (access and settings), `docs/security.md` (audit log), `docs/deployment.md`.

## Step 0: discovery (report, then wait for approval)

1. Inspect the folder. It should contain only this kit. List anything unexpected; do not overwrite anything.
2. Check the versions of Git, Python (`py --version`), Node and npm, and PostgreSQL (`psql --version`), and check whether a PostgreSQL service is running. Report what is missing, with exact Windows install steps for free tools only.
3. Propose:
   - the folder structure;
   - exact library versions (current stable);
   - how dev and test databases are created (`arms_dev` and `arms_test`; roles `app_owner` and `app_user`);
   - how `scripts\dev.ps1` and `scripts\check.ps1` will work.
4. List any decision you need from me. **Stop and wait for approval.**

## Build

**Backend**
- FastAPI app factory, `pydantic-settings` config (`APP_ENV`, database URLs, secret keys, file key, `UIDAI_CERT_PATH`, flags), and a `.env.example` with every variable documented.
- SQLAlchemy 2.0 with psycopg 3, a session-per-request dependency, and Alembic set up with the first migration:
  - `btree_gist` extension;
  - `users` (structure only);
  - `settings_versions`;
  - `audit_logs` with the hash chain;
  - grants for `app_user`.
- Core utilities with tests:
  - **Money:** paise from `Decimal` or `str` only; rupee formatting with Indian grouping; refuses floats.
  - **Time:** Asia/Kolkata business date and now; due-time calculation.
  - **Errors:** the error envelope from `api.md`, stable error codes.
  - **Request id** middleware and structured JSON logging that redacts personal fields.
  - **Audit writer:** canonical JSON and hash chain, plus `verify_chain()`.
- `GET /api/v1/health` (DB check and version).
- Seed command with obviously fake data: 1 owner, 2 staff, 5 drivers, 5 autos (no real-looking identity numbers).

**Frontend**
- Vite, React and TypeScript with Tailwind, React Router, TanStack Query, an API client with the error envelope and request id, an app shell (sidebar, top bar, responsive), and empty pages for each module in `requirements.md` §4.
- A small set of base components (button, input, select, table with pagination, dialog, toast, empty, loading and error states) and rupee and date formatters.

**Scripts and docs**
- `scripts\dev.ps1`: starts the API and Vite.
- `scripts\check.ps1`: ruff, mypy, pytest, eslint, tsc, vitest, pip-audit and npm audit. It fails on any error.
- `scripts\seed.ps1`.
- `README.md`: Windows setup from zero, using the commands above.
- Optional: a GitHub Actions workflow running the same checks (free).
- `deploy/` placeholders: `Caddyfile`, systemd unit templates and `deploy/README.md` from `docs/deployment.md` (no server work yet).

## Out of scope

Logins, drivers and every business feature.

## Tests to write first

- Money: `"300.00"` gives 30000 paise; adding paise stays an `int`; a float input raises an error; ₹120000.50 formats as `₹1,20,000.50`.
- Time: the business date at 23:59 and 00:01 IST; due time on a given date in IST stored as UTC.
- Audit: 3 entries chain correctly; changing one row's `after` makes `verify_chain()` fail; UPDATE or DELETE on `audit_logs` as `app_user` raises a database error.
- Health: returns 200 with the DB up.
- Settings: inserting a new version never updates the old row; "current" picks the latest effective version.

## Done when

- [ ] A fresh clone runs on Windows from the README commands alone.
- [ ] `.\scripts\check.ps1` is green.
- [ ] `alembic upgrade head` works on an empty database, and `alembic downgrade base` works too.
- [ ] `.env.example` lists every setting; no secrets are committed.
- [ ] Seed data loads and is visibly fake.

## You check

1. Run `.\scripts\dev.ps1`, open the app in the browser, and click through the empty pages on desktop and phone width.
2. Open `http://localhost:8000/api/v1/health`.
3. Run `.\scripts\check.ps1` yourself.
