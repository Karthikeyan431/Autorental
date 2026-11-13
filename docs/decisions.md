# Decisions log

Decisions made with the agency lead. Client-facing rule changes still need the client's written approval (see `business-rules.md`); items marked *awaiting client* are agency defaults until then.

## 12 November 2026 (before Week 1)

| # | Decision | Docs updated |
| --- | --- | --- |
| D1 | **Seed by week.** Week 1 seeds only the first settings version. Week 2 adds the owner and 2 staff with a dev-only password from `SEED_DEV_PASSWORD`. Week 3 adds drivers and Week 4 autos. The seed refuses to run when `APP_ENV=production`. | week-01 to week-04 |
| D2 | **Dependencies approved:** pydantic-settings, psycopg 3 (binary), uvicorn, httpx, python-multipart, pip-audit, APScheduler (development scheduling only), ESLint, Prettier. All must be free and open source and listed in `dependencies.md`. `check.ps1` runs ruff, mypy, pytest, pip-audit, eslint, tsc, vitest and npm audit. | CLAUDE.md, dependencies.md |
| D3 | **No server work until Week 8.** The client creates the Oracle account early, outside the code. | START_HERE.md |
| D4 | **KYC reopen** creates a new attempt in `under_review`. | business-rules (rule 12), kyc.md, week-03 |
| D5 | `unique_payment_reference` and `one_payment_per_statement_line` exclude both `rejected` and `reversed` payments. | data-model.md, rent-and-payments §5, week-06 |
| D6 | **Rejecting a payment** marks its allocations reversed with the reason "payment rejected". Allocations are never deleted. | business-rules (rule 11), data-model.md, rent-and-payments §5, week-06 |
| D7 | **Weekly rhythm** means paying in arrears for days already charged (Q16 stays). A weekly driver's charge is due on the first `weekly_pay_day` on or after the rent date, at the rent due time. Daily stays the default. *Awaiting client (N3).* | business-rules (rule 3), open-questions N3, rent-and-payments §1–2, data-model, week-05 |
| D8 | **Strong matching** also checks requests superseded in the last 7 days. Suggested days are always recomputed from the driver's oldest unpaid days at confirm time. | business-rules (rule 4), rent-and-payments §4, week-07 |
| D9 | **Permissions.** `drivers.restrict` covers suspend, reactivate and restrictions (owner by default, grantable). New codes: `adjustments.request` (staff on by default) and `adjustments.decide` (owner only, never grantable). | api.md, requirements §3, week-02, week-05 |
| D10 | **Ending an agreement** sets the vehicle to `available` at once. The `[]` exclusion constraint and the eligibility check enforce Q1, and the UI shows "available from <date>". | data-model.md, week-05 |
| D11 | `demo` is a dev-only method. No `updated_at` on insert-only tables. `week-01.md` uses `py -3.12`. | data-model.md, week-01 |

## 12 November 2026 (Week 1 plan approval)

| # | Decision | Docs updated |
| --- | --- | --- |
| D12 | **Extra free dependencies approved:** `tzdata` (never hardcode +05:30) and the frontend support packages. Versions are confirmed against the registries before installing, and the check date is recorded. | dependencies.md |
| D13 | `db-setup.ps1` may generate random dev passwords into `backend\.env`, which must be gitignored first. Passwords are never printed. | README.md |
| D14 | **Money display:** whole amounts show no `.00` (₹1,20,000); paise only when non-zero (₹1,20,000.50). Money is right-aligned in tables. Excel exports (Week 8) keep real numbers with a 2-decimal rupee number format. | CLAUDE.md (money), week-08 at build time |
| D15 | **No GitHub Actions for now;** `check.ps1` is the gate. Add the workflow if a private GitHub remote is added. | — |
| D16 | **Default privileges:** tables `app_owner` creates get `app_user`'s base grants automatically. Insert-only tables have UPDATE, DELETE and TRUNCATE revoked in their migration, with a test. | data-model.md |
| D17 | **Audit entries** are always written in the same database transaction as the change, with a rollback test. | data-model.md, CLAUDE.md |
| D18 | **Approved 13 Nov:** keep the npm override pinning `minimatch` 11.0.8 for the lint tools only (GHSA-g3hv-75wg-m249). Remove it once ESLint and typescript-eslint ship a fixed dependency. | dependencies.md |

## 13 November 2026 (Week 1 review)

| # | Decision | Docs updated |
| --- | --- | --- |
| D19 | **httpx2: not now.** Starlette's test client warns that `httpx` is deprecated in favour of `httpx2`. Keep `httpx` and revisit when Starlette drops `httpx` support (the warning becomes an error). | dependencies.md |
| D20 | **The rent due time has no default.** From Week 5, agreement activation and accrual refuse with `RENT_DUE_TIME_NOT_SET` ("Set the rent due time in Settings") while it is not set, with tests. | week-05, CLAUDE.md |
| D21 | **ISO weekdays everywhere:** 1 = Monday ... 7 = Sunday. Python uses `isoweekday()` (`app.core.time.iso_weekday`); the frontend uses `isoWeekday()`, and ESLint bans `getDay()`/`getUTCDay()`. Tested on both sides. | CLAUDE.md, data-model.md, week-05 |
| D22 | **`db-setup.ps1` never changes an existing role's password.** It only creates what is missing. With roles present and no `.env` it refuses (exit 2). `-RotatePasswords` rotates on request; `-DryRun` previews. Tested with dry runs against a temporary env file. | README.md, CLAUDE.md |

## 13 November 2026 (Week 2 plan approval)

| # | Decision | Docs updated |
| --- | --- | --- |
| D23 | **@hookform/resolvers 7.0.6** (MIT) approved. **qrcode 8.2** brought forward from Week 6 to draw the owner's TOTP QR as SVG; its licence was checked (BSD-3-Clause). | dependencies.md |
| D24 | **Common-password list:** SecLists `10k-most-common.txt` (MIT) is committed unmodified, with its source and licence recorded. | dependencies.md |
| D25 | **Audit log in Week 2:** a minimal owner-only list (`GET /audit-logs`, newest first, paginated) and `GET /audit-logs/verify`. Filters and export stay in Week 8. | api.md |
| D26 | **Owner TOTP enrolment** happens at the owner's first sign-in in the browser. Until enrolment is confirmed, the challenge token allows only `/auth/totp/setup` and `/auth/totp/confirm`. Recovery codes are shown once, and the owner must tick "I have saved these codes" to continue. | api.md, security.md |
| D27 | **Lockout response:** 429 `ACCOUNT_LOCKED` with "Too many attempts. Try again in 15 minutes." The IP throttle is 20 failures per 15 minutes (`LOGIN_IP_MAX_FAILURES`, `LOGIN_IP_WINDOW_MINUTES`). | api.md, .env.example |
| D28 | **GitHub Actions** (the remote is private): `.github/workflows/checks.yml` runs the `check.ps1` steps on ubuntu-latest with a PostgreSQL 17 service container, on push to master and on pull requests; a newer push cancels an older run. Only generated, per-run secrets. | README.md |
| D29 | **No `/me` endpoint** (CLAUDE.md): the signed-in user and their permissions come back from login, TOTP, confirm and refresh. | api.md |

## 13 November 2026 (Week 2 review)

| # | Decision | Docs updated |
| --- | --- | --- |
| D30 | **Refresh rate limit: Week 8 hardening.** `POST /auth/refresh` has no rate limit of its own yet (it already needs a valid, unrevoked refresh token and the CSRF header). Add a per-IP and per-session-family limit in Week 8 with the other hardening (security.md "Rate limits"). No change in Week 2. | week-08 at build time |
| D31 | **Multi-tab refresh:** the frontend runs every refresh inside a Web Lock (`navigator.locks`, lock `arms-auth-refresh`) and shares the result on a BroadcastChannel (`arms-auth`), so only one tab calls `/auth/refresh` at a time and the others use its new access token; sign-out is broadcast too. Prevents two tabs from tripping reuse detection. | — (code: `frontend/src/lib/refresh-coordinator.ts`) |
| D32 | **Password policy:** a password may not contain the user's own mobile number (the 10 digits, separators ignored) or name (the full name without spaces, or any word of it with 3 or more letters), ignoring case. Code `PASSWORD_TOO_PERSONAL` (422). Checked on change password, owner creation and staff creation with a given password. | api.md, security.md |

## 13 November 2026 (Week 3 plan approval)

| # | Decision | Docs updated |
| --- | --- | --- |
| D33 | **Who sees KYC.** KYC documents, KYC details, consents, decisions, eligibility and the KYC parts of the activity timeline are limited to the owner, the managing staff member and staff with `drivers.edit_any`; everyone else gets 404. The driver photo stays visible to all staff (N1). The staff KYC queue shows only the drivers they can decide on. Deciding also needs `kyc.decide`. | kyc.md, security.md |
| D34 | **Resubmission versus rejection.** `resubmission_required` lets staff start a new draft attempt; `rejected` and `approved` change only through an owner reopen. The UI says "Ask for documents again" versus "Reject (final; only the owner can reopen)". An `expired` licence also lets staff start a new attempt (a renewed card). | kyc.md |
| D35 | **Alerts table now.** `alerts` (with a `dedupe_key` so jobs are idempotent) is created in Week 3. Expiring licences show in the KYC queue's Expiring tab and as a dashboard count; per-user notifications stay in Week 7. | data-model.md, kyc.md |
| D36 | **Licence-number hashing:** HMAC-SHA256 with `LOOKUP_HMAC_KEY` (base64 of 32 bytes), refused in production when missing or weak, added by `db-setup.ps1` when missing and never replaced. It must be backed up with the other keys: losing or changing it breaks duplicate checks. | security.md, deployment.md, handover.md, .env.example |
| D37 | **Doc conflicts resolved.** (1) A licence number is unique **across drivers** (exclusion constraint on `(licence_number_hash =, driver_id <>)`), so a reopen may repeat it for the same driver. (2) A licence whose status is `expired` reports `LICENCE_EXPIRED`, not `LICENCE_NOT_APPROVED`. (3) Editing a driver you can see but may not edit gives 403 `DRIVER_NOT_EDITABLE`; 404 is only for records you may not see (such as KYC documents). | data-model.md, kyc.md, security.md |
| D38 | **Phone capture.** The primary photo and document capture is `<input type="file" accept="image/*" capture="environment">`, which opens the phone camera and works over plain http. The live `getUserMedia` camera is offered only in a secure context and hidden otherwise. | kyc.md |
| D39 | **Phone testing over Wi-Fi (development only).** `scripts\dev.ps1 -Lan` binds Vite to the LAN address and prints the URL; the firewall rule allows port 5173 on Private networks only. `DEV_INSECURE_COOKIES=true` drops the Secure flag on the refresh and CSRF cookies so sign-in survives reloads over http; the app refuses it unless `APP_ENV=development`. *Cookie part superseded by D43 (HTTPS; the setting was removed).* | README.md, CLAUDE.md, .env.example |
| D40 | **Images.** Decompression bombs are refused (`MAX_IMAGE_PIXELS` 40 million; Pillow's warning is treated as an error). PDFs are always served as attachments, never inline. | kyc.md, security.md |
| D41 | **Manual identity checklist** includes "Only the last 4 digits of the Aadhaar number are visible"; approval is refused (`CHECKLIST_INCOMPLETE`) unless it is ticked. | kyc.md |
| D42 | **Accepted ID documents (N12):** the setting `accepted_id_types` (default masked Aadhaar only) chooses from masked Aadhaar, voter ID and passport. For a non-Aadhaar document, `id_last4` holds the last 4 digits of that document's number. | open-questions.md |
| D43 | **Phone testing over HTTPS (replaces the cookie part of D39).** `scripts\dev.ps1 -Lan` serves Vite over HTTPS with `@vitejs/plugin-basic-ssl` (a self-signed certificate made on the PC, kept under `frontend/node_modules/.vite`, never in git), so the phone gets a secure context (Secure cookies, camera, Web Locks, `crypto.randomUUID`). `DEV_INSECURE_COOKIES` was removed; cookies are always Secure. Over plain http the app still works where it can (request-id and refresh-lock fallbacks) and shows an "Open this app over HTTPS" banner. Production is unchanged (Caddy). | README.md, handover.md, security.md |
| D44 | **Errors and logs.** Auth endpoints never trigger the silent refresh. Screens show the server's message for known codes, and "Something went wrong (ref: …)" only for unexpected errors (the request id, or a short client ref logged to the console). The API logs one line per request; validation errors are stripped of `input`/`ctx` globally. In `-Lan` mode Vite forwards the client IP, trusted only from 127.0.0.1. | security.md |
