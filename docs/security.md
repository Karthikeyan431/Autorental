# Security

Target: OWASP ASVS level 1 at launch. The app holds identity documents and money records, so the defaults below are deliberately strict.

## Sign-in and sessions

- Login with mobile number or email and a password. Passwords are hashed with **Argon2id**. Minimum 10 characters, the 10,000 most common passwords are blocked (bundle a free list in the repo), and a password may not contain the user's own mobile number or name (D32).
- **Owner 2-step sign-in:** a TOTP code from any free authenticator app (`pyotp`), required for the owner account. Generate recovery codes at setup and store them hashed.
- **Access token:** 15 minutes, held in memory in the browser.
- **Refresh token:** 7 days, in an `httpOnly`, `Secure`, `SameSite=Strict` cookie, rotated on every use. Its hash is stored in `sessions`. Reusing an old token revokes the whole session family.
- Every request re-checks that the user is active, so deactivating staff takes effect on their next click.
- Tabs take turns refreshing (Web Locks) and share the new access token (BroadcastChannel), so two open tabs never trip reuse detection (D31).
- **Lockout and throttling:** 5 failed logins lock the account for 15 minutes; logins are also throttled per IP address.
- The owner resets staff passwords, which forces a change at the next login. Email reset links are optional (free SMTP account) and come later.

## Authorisation

- Permission codes are listed in `api.md`. Every route declares its permission, and a test lists every route and fails if one has no declared permission.
- Staff can edit only the drivers they manage (N1 default); reads follow N1. Editing a driver you can see but may not edit gives 403 `DRIVER_NOT_EDITABLE` (D37).
- Return 404, not 403, for a record the user is not allowed to see. KYC documents, details, consents and decisions are visible only to the owner, the managing staff member and staff with `drivers.edit_any` (D33). From Week 4, document images and KYC decisions are for the owner and the current manager only (D46), and identity fields are masked, encrypted at rest (address, dates of birth, licence number) and revealed one field at a time with an audit entry (D45, D46).

## Data protection

- Never store a full Aadhaar number (see `kyc.md`).
- Encrypt licence numbers, the driver's address and date of birth, the date of birth on the licence (from Week 4, D46) and the owner's TOTP secret at application level (AES-256-GCM, `cryptography`). Keys come from the environment, with key rotation through `key_id`.
- **Back up `FIELD_ENCRYPTION_KEY` separately from the database backups.** Without it, every encrypted field (licence numbers, addresses, dates of birth, the owner's TOTP secret) is unreadable, even with a perfect database backup. A key stored with the backups would let anyone holding a backup read those fields. The backup setup comes in Week 8 (`handover.md`, `deployment.md`).
- Licence-number duplicate checks use HMAC-SHA256 with `LOOKUP_HMAC_KEY`, never a plain hash. This key is never rotated; back it up with the other keys (D36).
- No field accepts a 12-digit (Aadhaar-like) number: identity fields, names, addresses and reasons all refuse it, and so do the licence number, the consent notice version and an auto's registration number (which must contain letters). `tests/api/test_no_full_aadhaar.py` inspects every request model, so a new text field without the check fails the build; its probes start with 2-9 like real numbers and are built at runtime, never written as literals.
- Documents are encrypted on disk, served only through the audited endpoint, and never given public URLs.
- Logs never contain names, mobiles, Aadhaar or licence numbers, addresses, tokens or passwords. Log user ids and request ids.
- Audit entries, KYC history and the activity timeline never hold a masked value (address, dates of birth, licence number, the ID document's date or year of birth, gender): only which field changed or was revealed (D49). `audit_logs` is insert-only, so a value written there could never be removed.
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
- **Uploads:** check the real file type and size; strip EXIF; refuse decompression bombs; never serve uploads inline as HTML, and serve PDFs only as attachments (D40).
- **Cookies are always Secure**, in every environment. Phone testing (`dev.ps1 -Lan`) uses HTTPS with a self-signed development certificate instead of dropping the flag (D43; `DEV_INSECURE_COOKIES` was removed).
- **Client IP:** taken from `X-Forwarded-For` only when the connection comes from the trusted local proxy (`--forwarded-allow-ips 127.0.0.1`: the Vite proxy in development, Caddy in production); otherwise the connection's own address (D44).
- **Logs:** one access line per request (method, path without the query string, status, duration, request id), never bodies. Validation errors never carry pydantic's `input` or `ctx`, in responses or logs (D44).
- **Dependencies:** `pip-audit` and `npm audit` (both free) run in `check.ps1`.

## Backups and recovery (free)

- Nightly `pg_dump` plus the documents folder, compressed and encrypted with `age` (free, open source). Copy it to Oracle Object Storage (Always Free) and keep the last 14.
- Weekly: the owner downloads the latest encrypted backup to their own computer from the Settings page.
- Week 8 includes a timed **restore test** to a fresh server, written up in `docs/deployment.md`.
