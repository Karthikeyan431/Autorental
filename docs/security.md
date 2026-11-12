# Security

Target: OWASP ASVS level 1 at launch. The app holds identity documents and money records, so the defaults below are deliberately strict.

## Sign-in and sessions

- Login with mobile number or email and a password. Passwords are hashed with **Argon2id**. Minimum 10 characters, and the 10,000 most common passwords are blocked (bundle a free list in the repo).
- **Owner 2-step sign-in:** a TOTP code from any free authenticator app (`pyotp`), required for the owner account. Generate recovery codes at setup and store them hashed.
- **Access token:** 15 minutes, held in memory in the browser.
- **Refresh token:** 7 days, in an `httpOnly`, `Secure`, `SameSite=Strict` cookie, rotated on every use. Its hash is stored in `sessions`. Reusing an old token revokes the whole session family.
- Every request re-checks that the user is active, so deactivating staff takes effect on their next click.
- **Lockout and throttling:** 5 failed logins lock the account for 15 minutes; logins are also throttled per IP address.
- The owner resets staff passwords, which forces a change at the next login. Email reset links are optional (free SMTP account) and come later.

## Authorisation

- Permission codes are listed in `api.md`. Every route declares its permission, and a test lists every route and fails if one has no declared permission.
- Staff can edit only the drivers they manage (N1 default); reads follow N1.
- Return 404, not 403, for a record the user is not allowed to see.

## Data protection

- Never store a full Aadhaar number (see `kyc.md`).
- Encrypt licence numbers and the owner's TOTP secret at application level (AES-256-GCM, `cryptography`). Keys come from the environment, with key rotation through `key_id`.
- Documents are encrypted on disk, served only through the audited endpoint, and never given public URLs.
- Logs never contain names, mobiles, Aadhaar or licence numbers, addresses, tokens or passwords. Log user ids and request ids.
- Consent is recorded before KYC. Build to the DPDP Rules 2025 now: their main obligations apply from 13 May 2027.

## Audit log

- Insert-only `audit_logs` with a SHA-256 hash chain (`prev_hash`, `hash` over canonical JSON). The `app_user` database role has no UPDATE, DELETE or TRUNCATE on it.
- `GET /audit-logs/verify` recomputes the chain.
- **Audited actions:** sign-in success and failure, user and permission changes, settings versions, driver create, edit and reassign, consent, KYC decisions and reopens, document views, agreement activate and end, payments (record, allocate, approve, reject, reverse), adjustments, advance, statement imports and matches, escalations.

## Web hardening

- **HTTP headers** (set in Caddy and the app): HSTS, a strict Content-Security-Policy (no inline scripts), `X-Content-Type-Options`, `Referrer-Policy: same-origin`, `Permissions-Policy` allowing `camera` only for the app's own origin.
- **CORS:** only the app's own origin.
- **CSRF:** cookie-based refresh plus `SameSite=Strict`, and a double-submit token on `/auth/refresh`.
- **Rate limits:** login, refresh, uploads and statement import.
- **Uploads:** check the real file type and size; strip EXIF; never serve uploads inline as HTML.
- **Dependencies:** `pip-audit` and `npm audit` (both free) run in `check.ps1`.

## Backups and recovery (free)

- Nightly `pg_dump` plus the documents folder, compressed and encrypted with `age` (free, open source). Copy it to Oracle Object Storage (Always Free) and keep the last 14.
- Weekly: the owner downloads the latest encrypted backup to their own computer from the Settings page.
- Week 8 includes a timed **restore test** to a fresh server, written up in `docs/deployment.md`.
