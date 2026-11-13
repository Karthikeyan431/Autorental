# API

REST under `/api/v1`, JSON in and out, OpenAPI docs in development only.
- **Lists:** take `search`, filters, `page` and `page_size` (max 100), and return `{items, total, page, page_size}`.
- **Write endpoints:** check the permission, validate with Pydantic, run in one transaction, and write an audit entry.
- **Creates** that move money accept an `Idempotency-Key` header.

## Error format

```json
{ "error": { "code": "LICENCE_EXPIRED", "message": "The driver's licence expired on 2026-10-31.", "details": {"reasons": ["LICENCE_EXPIRED"]}, "request_id": "8f3c..." } }
```

Status codes:
- 400: malformed request.
- 401: not signed in.
- 403: no permission.
- 404: not found, or not visible to you.
- 409: a business rule refused the action. Use stable `code` values.
- 422: validation error.
- 429: rate limited.

## Modules

| Module | Endpoints | Who |
| --- | --- | --- |
| Auth | `POST /auth/login` (mobile or email + password) · `POST /auth/totp` (owner second step) · `POST /auth/refresh` · `POST /auth/logout` · `POST /auth/change-password` · `POST /auth/totp/setup` and `/auth/totp/confirm` (owner) | Everyone |
| Users | `GET, POST /users` · `GET, PATCH /users/{id}` · `POST /users/{id}/deactivate` · `/reactivate` · `/reset-password` · `PUT /users/{id}/permissions` · `GET /permissions` (code catalogue) | Owner |
| Settings | `GET /settings/current` · `GET /settings/versions` · `POST /settings` (new version) | Owner (read: everyone) |
| Drivers | `GET, POST /drivers` · `GET /drivers/managers` · `GET, PATCH /drivers/{id}` · `POST /drivers/{id}/photo` · `POST /drivers/{id}/manager` (owner) · `GET /drivers/{id}/manager-history` · `GET /drivers/{id}/timeline` · `GET, POST /drivers/{id}/restrictions` · `POST /restrictions/{id}/lift` · `POST /drivers/{id}/suspend`, `/reactivate` | Staff (edit: own drivers, N1); owner |
| Consents | `POST /drivers/{id}/consents` · `POST /consents/{id}/withdraw` | Staff, owner |
| KYC | `GET /kyc/queue?bucket=` · `GET /kyc/queue/counts` · `GET /drivers/{id}/kyc` · `POST /drivers/{id}/kyc/{identity\|licence}/attempts` · `GET /kyc/attempts/{id}` · `PUT /kyc/attempts/{id}/identity-details` · `PUT /kyc/attempts/{id}/licence-details` · `POST /kyc/attempts/{id}/documents` · `POST /kyc/attempts/{id}/uidai-qr` (flagged) · `POST /kyc/attempts/{id}/uidai-app-attestation` · `POST /kyc/attempts/{id}/parivahan-lookup` · `POST /kyc/attempts/{id}/submit` · `POST /kyc/attempts/{id}/decision` · `POST /kyc/attempts/{id}/reopen` (owner) · `GET /drivers/{id}/eligibility` | Staff, owner |
| Documents | `GET /documents/{id}/content` (streamed, audited) · `GET /documents/{id}` (metadata) | By permission |
| Vehicles | `GET, POST /vehicles` · `GET, PATCH /vehicles/{id}` · `POST /vehicles/{id}/status` · `GET, POST /vehicles/{id}/compliance` · `GET, POST /vehicles/{id}/maintenance` | Staff, owner |
| Agreements | `GET, POST /agreements` · `GET /agreements/{id}` · `POST /agreements/{id}/activate` · `/end` · `/cancel` · `GET /agreements/{id}/print` (PDF) · `POST /agreements/{id}/signed-copy` | Staff, owner |
| Rent | `GET /drivers/{id}/ledger?from&to` · `GET /rent/overdue` · `POST /rent/charges/{id}/adjustments` (`adjustments.request`) · `POST /adjustments/{id}/decision` (owner, `adjustments.decide`) · `POST /jobs/accrue` (owner, manual run) | Staff, owner |
| Pay requests | `GET /pay-requests?date=` · `POST /pay-requests/generate` (idempotent) · `GET /pay-requests/{id}` (link, QR, WhatsApp URL) · `GET /pay-requests/{id}/qr.png` · `POST /pay-requests/{id}/sent` | Staff, owner |
| Payments | `GET, POST /payments` · `GET /payments/{id}` · `PUT /payments/{id}/allocations` (confirm days) · `POST /payments/approve` (ids[]) · `POST /payments/{id}/reject` · `GET /payments/{id}/receipt.pdf` · `POST /payments/{id}/reversal-requests` · `POST /reversal-requests/{id}/decision` (owner) | Staff record; owner approves |
| Statements | `GET, POST /bank-statements` (upload) · `GET, POST /bank-profiles` · `GET /bank-statements/{id}/lines` · `POST /statement-lines/{id}/match` · `POST /statement-lines/{id}/ignore` · `POST /bank-statements/{id}/confirm-strong` | Owner; staff with `statements.upload` |
| Advance | `GET /drivers/{id}/advance` · `POST /advance/adjustments` · `POST /advance/{id}/decision` (owner) | Staff request; owner decides |
| Escalations | `GET, POST /escalations` (POST: owner) · `GET /escalations/{id}` · `POST /escalations/{id}/events` · `POST /escalations/{id}/close` (owner) · `GET /escalations/suggested` (owner) | Owner; assigned staff |
| Notifications | `GET /notifications` · `POST /notifications/{id}/read` · `POST /push/subscriptions` · `DELETE /push/subscriptions/{id}` · `GET /push/vapid-public-key` | Everyone |
| Dashboard | `GET /dashboard/owner` · `GET /dashboard/staff` | Owner; staff |
| Reports | `GET /reports/{key}?from&to&driver_id&vehicle_id&staff_id&format=json\|xlsx` | Owner; staff own drivers (N1) |
| Audit | `GET /audit-logs?entity_type&entity_id&actor_id&from&to` · `GET /audit-logs/verify` (hash chain) | Owner |
| Health | `GET /health` (no auth; DB connectivity, version) | Public |

## Sign-in (Week 2)

- `POST /auth/login` `{login, password}`: `login` is a mobile number (any of `9000000001`, `+91 90000 00001`, `09000000001`) or an email.
  - Staff: `{status: "ok", access_token, token_type, expires_in: 900, user}`, plus the cookies below.
  - Owner: `{status: "totp_required" | "totp_setup_required", challenge_token}` (5 minutes). A `totp_setup_required` challenge works only for `/auth/totp/setup` and `/auth/totp/confirm` (D26).
- `POST /auth/totp` `{challenge_token, code}` or `{challenge_token, recovery_code}`. A code is refused if its 30-second step was already used.
- `POST /auth/totp/setup` `{challenge_token}` returns `{secret, otpauth_uri, qr_svg}`. `POST /auth/totp/confirm` `{challenge_token, code}` returns the signed-in response plus `recovery_codes` (10, shown once, stored as hashes).
- `user` in every signed-in response is the profile and effective permissions; there is no `/me` endpoint (D29).
- **Cookies:** `arms_refresh` (httpOnly, Secure, SameSite=Strict, path `/api/v1/auth`, 7 days, rotated on every refresh) and `arms_csrf` (readable, Secure, SameSite=Strict). `POST /auth/refresh` needs the header `X-CSRF-Token` equal to `arms_csrf`.
- Every other route takes `Authorization: Bearer <access_token>`.

| Code | Status | When |
| --- | --- | --- |
| `UNAUTHENTICATED` | 401 | No, bad or expired token; user inactive; session revoked |
| `INVALID_CREDENTIALS` | 401 | Wrong login or password, or inactive account (same answer for each) |
| `ACCOUNT_LOCKED` | 429 | 5 failures (password or TOTP): "Too many attempts. Try again in 15 minutes." |
| `IP_THROTTLED` | 429 | `LOGIN_IP_MAX_FAILURES` failures from one IP within `LOGIN_IP_WINDOW_MINUTES` |
| `TOTP_INVALID` | 401 | Wrong, expired or reused code, or a used/unknown recovery code |
| `CHALLENGE_INVALID` | 401 | Expired challenge, or the wrong step for this owner |
| `CSRF_FAILED` | 403 | Missing or wrong `X-CSRF-Token` on refresh |
| `REFRESH_INVALID` / `REFRESH_REUSED` | 401 | Unknown or expired refresh token / a rotated token reused (the whole session family is revoked) |
| `PASSWORD_CHANGE_REQUIRED` | 403 | Any route except change-password and logout, after a reset |
| `PASSWORD_TOO_SHORT` / `PASSWORD_TOO_LONG` / `PASSWORD_TOO_COMMON` / `PASSWORD_TOO_PERSONAL` | 422 | Password policy (D32: no own mobile or name) |
| `CURRENT_PASSWORD_INCORRECT` / `PASSWORD_UNCHANGED` | 409 | Change password |
| `FORBIDDEN` | 403 | Missing permission |
| `STAFF_LIMIT_REACHED` | 409 | Create or reactivate beyond `staff_limit` (rule 16) |
| `PERMISSION_NOT_GRANTABLE` | 409 | An owner-only code in `PUT /users/{id}/permissions` |
| `OWNER_PERMISSIONS_FIXED`, `OWNER_CANNOT_BE_DEACTIVATED`, `OWNER_PASSWORD_RESET_NOT_ALLOWED` | 409 | Owner account protections |
| `MOBILE_TAKEN` / `EMAIL_TAKEN` | 409 | Duplicate contact details |
| `USER_ALREADY_ACTIVE` / `USER_ALREADY_INACTIVE` | 409 | Toggle on an account already in that state |
| `NO_SETTINGS_CHANGED` | 409 | `POST /settings` with no fields |
| `RENT_DUE_TIME_REQUIRED` | 422 | The first settings version without a rent due time |

`GET /settings/current` returns `null` until the first version is saved. `POST /settings` takes the changed fields plus an optional `reason`, and returns the new version (201).

## Drivers and KYC (Week 3)

- `GET /drivers` filters: `search`, `status`, `managed_by`, `mine=true`, `kyc=verified|not_verified` (the KYC filter only returns drivers whose KYC you may see). KYC statuses in driver responses are `null` for users who cannot see that driver's KYC (D33).
- `GET /kyc/queue?bucket=pending|under_review|resubmission|rejected|expiring` and `GET /kyc/queue/counts` (the dashboard counts use the same query, rule 9).
- `POST /kyc/attempts/{id}/documents` is multipart: `doc_type` (`id_front`, `id_back`, `licence_front`, `licence_back`) and `file`. `POST /drivers/{id}/photo` is multipart: `file`.
- `POST /kyc/attempts/{id}/decision` `{decision: approve|reject|resubmit, checklist: {key: bool}, reason}`. `POST /kyc/attempts/{id}/reopen` `{reason}` returns the new attempt (201).
- `GET /documents/{id}/content?purpose=view|download`: streamed, `Cache-Control: no-store`; PDFs always `Content-Disposition: attachment`.
- The licence number is never returned; responses carry `licence_number_masked` (last 4 characters).

| Code | Status | When |
| --- | --- | --- |
| `NOT_FOUND` | 404 | A driver, attempt or document that does not exist, or KYC you may not see (D33) |
| `DRIVER_NOT_EDITABLE` | 403 | Editing (or capturing KYC for) a driver you can see but do not manage (D37) |
| `FIELD_NOT_EDITABLE` | 403 | Week 4: a masked field in an edit by someone who is not the owner or the current manager (N17, D46) |
| `KYC_DECIDE_NOT_ALLOWED` | 403 | Week 4: a KYC decision by someone who is not the owner or the current manager (N16, D46) |
| `REVEAL_NOT_ALLOWED` / `REVEAL_RATE_LIMITED` | 403 / 429 | Week 4: a reveal by someone who is not the owner or the current manager / over `reveal_limit_per_hour` (D45, N18) |
| `MOBILE_TAKEN` | 409 | Another driver has this mobile (after normalising to +91) |
| `LICENCE_TAKEN` | 409 | Another driver has this licence number (after normalising) |
| `INVALID_LICENCE_NUMBER` | 422 | Not 6 to 20 letters and digits after removing spaces and dashes |
| `MANAGER_NOT_AVAILABLE` / `SAME_MANAGER` | 409 | Change manager to an inactive or unknown user / the current manager |
| `CONSENT_REQUIRED` | 409 | A KYC attempt before a `kyc` consent (or after it was withdrawn) |
| `KYC_METHOD_NOT_AVAILABLE` | 409 | A method other than `manual` (Week 4 adds the others; a UIDAI method whose flag is off gives 404, D47) |
| `KYC_ATTEMPT_OPEN` / `KYC_REOPEN_REQUIRED` | 409 | A new attempt while one is open / after approval or rejection (owner reopen only, D34) |
| `ATTEMPT_NOT_EDITABLE` | 409 | Details or uploads on an attempt that is no longer a draft |
| `KYC_INCOMPLETE` | 409 | Submit without details or a required document (`details.missing`) |
| `KYC_INVALID_TRANSITION` | 409 | Deciding a draft, or reopening something not approved or rejected |
| `CHECKLIST_INCOMPLETE` | 409 | Approve without every required checklist item (`details.missing`) |
| `CHECKLIST_UNKNOWN_ITEM` / `REASON_REQUIRED` | 422 | A checklist key that does not belong / reject or resubmit without a reason |
| `ID_TYPE_NOT_ACCEPTED` | 409 | An ID document not in the setting `accepted_id_types` (N12) |
| `DOC_TYPE_NOT_ALLOWED` | 422 | A document type that does not belong to this check |
| `FILE_TYPE_NOT_ALLOWED` / `FILE_TOO_LARGE` / `IMAGE_TOO_LARGE` | 422 | Not a real JPEG, PNG or PDF / over 5 MB (images) or 10 MB (PDFs) / over 40 megapixels |
| `DRIVER_STATUS_UNCHANGED` / `RESTRICTION_ALREADY_LIFTED` / `CONSENT_ALREADY_WITHDRAWN` | 409 | Repeating a status change |

## Report keys

`driver-ledger`, `vehicle-summary`, `daily-collection` (by date received and by rent day, Q19), `monthly-collection`, `outstanding`, `overdue`, `payment-history`, `approvals`, `advance-balances`, `active-agreements`, `kyc-status`, `escalations`, `staff-performance`.

Every report total must equal the ledger queries; add a test per report.

## Permission codes (starting list)

`drivers.create`, `drivers.edit_own`, `drivers.edit_any`, `drivers.reassign` (owner), `drivers.restrict`, `kyc.decide`, `kyc.reopen` (owner), `vehicles.manage`, `agreements.manage`, `payrequests.send`, `payments.record`, `payments.approve` (owner), `payments.reverse_decide` (owner), `adjustments.request`, `adjustments.decide` (owner), `statements.upload`, `advance.decide` (owner), `escalations.raise` (owner), `escalations.work`, `reports.all`, `settings.manage` (owner), `users.manage` (owner), `audit.view` (owner).

Owner-only codes cannot be granted to staff.

| Code | Covers | Staff default | Grantable to staff |
| --- | --- | --- | --- |
| `drivers.restrict` | Place or lift a restriction; suspend or reactivate a driver | Off | Yes |
| `adjustments.request` | Request a charge adjustment | On | n/a |
| `adjustments.decide` | Decide a charge adjustment | Off | Never (owner only) |
