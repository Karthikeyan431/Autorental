# Week 2: Sign-in, owner and staff, permissions

**Goal:** a secure two-role system: the owner and up to 10 staff, with permissions, owner 2-step sign-in, and every action audited.

**Read first:** `docs/security.md`, `docs/requirements.md` §3, `docs/api.md` (Auth, Users, Settings, permission codes), `docs/business-rules.md` (rules 11 and 16), `docs/open-questions.md` (N1, N10, Q28).

## Build

**Backend**
- `users`, `user_permissions` and `sessions` tables, with exactly one owner (partial unique index).
- Argon2id hashing, the common-password list, and the minimum length.
- **Login:**
  - Login by mobile or email.
  - Lockout after 5 failures for 15 minutes, plus a per-IP throttle.
  - A 15-minute access JWT and a rotating 7-day refresh cookie with reuse detection.
  - Logout revokes the session.
- **Owner TOTP:** setup with a QR code for the authenticator app, confirmation, recovery codes (stored hashed), and a required second step at owner login.
- Every request re-checks `is_active`. Deactivation revokes all sessions.
- **Staff management (owner only):**
  - Create, edit, deactivate and reactivate staff.
  - Reset a password, which forces a change at next login.
  - Set permissions from the code list.
  - Owner-only codes can never be granted.
- **Staff limit:** the `staff_limit` setting (default 10) is enforced on create and reactivate (rule 16).
- **Settings API:** a new version on each change; owner only.
- A route permission registry, plus a test that fails if any route has no declared permission.
- Audit entries for logins (success and failure), user changes, permission changes and settings changes.
- A first-run command to create the owner account (prompted in the terminal; no default password in code).

**Frontend**
- Sign-in, the owner TOTP step, forced password change, and session refresh handling.
- Staff list and form, with an activate or deactivate toggle and a permissions editor.
- Settings page (versioned: shows the history).
- Role-aware navigation, and the dashboard shell with placeholders for the owner and staff dashboards.

## Out of scope

Drivers, KYC and money.

## Tests to write first

- Wrong password 5 times locks the account; correct after 15 minutes works; IP throttle triggers.
- Refresh rotation: using an old refresh token revokes the whole family.
- A deactivated staff member's existing access token gets 401 on the next request.
- Owner login without a TOTP code is refused; with a valid code it succeeds; a reused code within the same window is refused.
- Staff calling an owner-only endpoint gets 403. Granting an owner-only code is refused (409).
- 10 active staff exist, so creating an 11th is refused with code `STAFF_LIMIT_REACHED`; after the owner raises the limit to 11, it works; reactivating beyond the limit is refused.
- Every route has a declared permission (registry test).
- Audit entries exist for each audited action, and the chain verifies.

## Done when

- [ ] All tests above pass and `check.ps1` is green.
- [ ] The owner can create staff, set permissions, deactivate one, and see the audit entries.
- [ ] No password, token or TOTP secret appears in logs.

## You check

1. Create the owner from the terminal command and set up TOTP on your phone.
2. Create 2 staff, sign in as one in a private window, deactivate them from the owner window, and click again as staff: you are signed out.
3. Try a wrong password 5 times: the account locks.
