# Data model (PostgreSQL 17)

Conventions:
- Primary keys are `BIGINT GENERATED ALWAYS AS IDENTITY`. Use a public-facing `code` where people need one (driver code, agreement number, receipt number).
- Money is `BIGINT` paise with `CHECK (... >= 0)` or `> 0` as appropriate.
- Timestamps are `timestamptz` (UTC); rent dates are `date` (Asia/Kolkata calendar).
- `created_at` on every table, and `updated_at` on every table that can be updated. Insert-only tables (`audit_logs`, `settings_versions`, `rent_charges`, `kyc_events`, `escalation_events`, `document_access_log`) have no `updated_at`. Status columns are `text` with `CHECK (status IN (...))`.
- The KYC method `demo` exists only for `APP_ENV` `development` and `test` (see `kyc.md` and Week 4); it is not one of the rule 8 methods.
- Personal fields marked *(enc)* are encrypted at application level (AES-256-GCM, key from env, `key_id` stored).
- Outstanding, overdue and balances are **never stored**; they are computed from charges, adjustments, allocations and payment status.

## Access and settings

| Table | Key columns | Notes |
| --- | --- | --- |
| users | name, mobile (unique), email (unique, nullable), password_hash (Argon2id), role (`owner` / `staff`), is_active, must_change_password, totp_secret *(enc, owner)*, failed_logins, locked_until, last_login_at | Exactly one owner (partial unique index on role = 'owner') |
| user_permissions | user_id, permission_code, granted_by, granted_at | Owner-only codes cannot be granted (service check plus a CHECK list) |
| sessions | user_id, refresh_token_hash, family_id, expires_at, revoked_at, ip, user_agent | Refresh rotation; reuse of an old token revokes the family |
| audit_logs | occurred_at, actor_id, action, entity_type, entity_id, before, after (redacted JSON), reason, ip, request_id, prev_hash, hash | Insert-only. The app DB role gets INSERT and SELECT only. Hash chain over the canonical JSON of each row |
| settings_versions | effective_from, rent_due_time, due_day_offset (Q9, default 0), licence_alert_days (30), vehicle_alert_days (30), permitted_licence_classes, advance_adjustments_enabled, refunds_enabled (false), staff_limit (10), business_name, business_address, business_upi_id, upi_payee_name, whatsapp_template, pay_request_time (08:00), weekly_pay_day (Monday), escalation_suggest_after_days (1), weekly_mdr_warning_paise (200000), created_by | Never updated; each change inserts a version. "Current" = latest effective_from ≤ now |
| notifications | user_id, kind, entity_type, entity_id, message, created_at, read_at | In-app alerts |
| push_subscriptions | user_id, endpoint (unique), p256dh, auth, created_at, revoked_at | Web Push |

## Drivers and KYC

| Table | Key columns | Notes |
| --- | --- | --- |
| drivers | code (unique, e.g. D0042), full_name, mobile (unique, normalised +91), alt_mobile, address, date_of_birth, emergency_name, emergency_mobile, photo_document_id, account_status (`active` / `suspended` / `inactive`), payment_rhythm (`daily` / `weekly`), created_by (immutable), managed_by, registered_at | `created_by` is set once; a trigger or service guard refuses changes |
| driver_manager_history | driver_id, staff_id, from_at, to_at, changed_by, reason | One open row per driver (to_at IS NULL, partial unique) |
| driver_restrictions | driver_id, reason, is_blocking, placed_by, placed_at, lifted_by, lifted_at | Eligibility condition 5 |
| consents | driver_id, purpose (`kyc`, `aadhaar_qr`), notice_version, method (`in_person_signed`, `in_person_checkbox`), captured_by, captured_at, withdrawn_at | Required before any KYC step |
| kyc_checks | driver_id, check_type (`identity` / `licence`), attempt_no, method (`uidai_qr` / `uidai_app_attested` / `parivahan_lookup` / `manual` / `demo`), status (`draft` / `submitted` / `under_review` / `approved` / `rejected` / `resubmission_required` / `expired`), is_simulated, evidence (minimal JSON), review_checklist (JSON), submitted_at, reviewed_by, reviewed_at, decision_reason, is_current | One row per attempt; partial unique on (driver_id, check_type) where is_current |
| kyc_events | kyc_check_id, from_status, to_status, actor_id, at, reason | History |
| identity_details | kyc_check_id, document_type, id_last4, name_on_document, dob_or_yob, gender, qr_signature_valid (bool, nullable), photo_match_confirmed_by | **Never** a full Aadhaar number. No QR payload or address stored unless the legal adviser approves (N13) |
| licence_details | kyc_check_id, licence_number *(enc)*, licence_number_hash (unique, for duplicate checks), name_on_licence, date_of_birth, issue_date, valid_until_non_transport, valid_until_transport, vehicle_classes (text[]), issuing_authority, lookup_status_text, looked_up_at, lookup_screenshot_document_id | Validity drives eligibility and alerts |
| documents | owner_type, owner_id, doc_type, storage_key, sha256, mime_type, size_bytes, key_id, uploaded_by, uploaded_at, retention_until, purged_at | Encrypted files on disk outside the web root; served only through an authenticated, audited endpoint |
| document_access_log | document_id, user_id, at, ip, purpose | Every view or download |

## Autos

| Table | Key columns | Notes |
| --- | --- | --- |
| vehicles | registration_number (unique, normalised), make, model, year, fuel_type, status (`available` / `rented` / `maintenance` / `inactive`), notes | Only the agreements service sets `rented` and back. Ending an agreement sets `available` at once; the `[]` exclusion constraint and the eligibility check stop a new agreement starting on the return day (Q1), and the UI shows "available from <return day + 1>" |
| vehicle_compliance | vehicle_id, kind (`insurance` / `fitness` / `permit` / `pollution`, Q29), number, valid_from, valid_until, document_id | Expiry alerts |
| maintenance_records | vehicle_id, started_on, ended_on, description, cost_paise, recorded_by | |

## Agreements and rent

| Table | Key columns | Notes |
| --- | --- | --- |
| agreements | agreement_no (unique), driver_id, vehicle_id, status (`draft` / `active` / `ended` / `cancelled`), start_date, end_date, daily_rent_paise (> 0), advance_required_paise, terms_version, signed_document_id, created_by, activated_by, activated_at, ended_by, ended_at, end_reason | Rate fixed per agreement (Q10) |
| rent_charges | agreement_id, driver_id, rent_date, amount_paise, due_at, settings_version_id, created_at | Never updated. `UNIQUE (agreement_id, rent_date)`. `due_at` follows the driver's payment rhythm at accrual time (see `rent-and-payments.md` §1) |
| charge_adjustments | rent_charge_id, amount_paise (signed; negative = waiver), reason, status (`pending` / `approved` / `rejected`), requested_by, decided_by, decided_at | Only approved adjustments count |

## Pay requests, payments, statements

| Table | Key columns | Notes |
| --- | --- | --- |
| pay_requests | driver_id, agreement_id, period_start, period_end, amount_paise, reference_code (e.g. `R00421112`; unique with period_start), suggested_charge_ids (bigint[]), status (`open` / `paid` / `superseded` / `cancelled`), created_at, sent_by, sent_at, send_count | One open request per driver per period (unique on driver_id, period_start where status = 'open') |
| payments | driver_id, agreement_id, amount_paise (> 0), method (`upi` / `cash`), source (`pay_request` / `upi_direct` / `cash_office`), purpose (`rent` / `advance_deposit`), reference (UPI ref / UTR), received_on, pay_request_id, statement_line_id (unique, nullable), proof_document_id, recorded_by, status (`awaiting_approval` / `approved` / `rejected` / `reversed`), approved_by, approved_at, rejection_reason, receipt_no (unique, set at approval), idempotency_key (unique) | Unique (method, reference) where reference is not null and status is not `rejected` or `reversed` |
| payment_allocations | payment_id or advance_transaction_id (exactly one), rent_charge_id, amount_paise (> 0), confirmed_by, confirmed_at, reversed_at, reversed_by, reversal_reason | Counts toward balances only when the payment is approved (or the advance transaction is approved) and the allocation is not reversed. Never deleted: rejecting a payment marks its allocations reversed with the reason "payment rejected" |
| reversal_requests | payment_id or allocation_id, reason, requested_by, decided_by, decision, decided_at | Q4 default: staff request, owner decides |
| receipt_counters | financial_year (e.g. `2026-27`), last_number | Row-locked when issuing, so there are no gaps: `RCPT/2026-27/000123` |
| bank_statement_imports | file_document_id, file_sha256 (unique), bank_profile_id, period_from, period_to, uploaded_by, uploaded_at, line_count | A duplicate file upload is refused |
| bank_profiles | name, column mapping JSON (date, narration, reference, credit, debit, balance, date format, header row) | Saved once per bank |
| bank_statement_lines | import_id, line_no, txn_date, amount_paise (credits only kept), narration, bank_reference, fingerprint (unique: date + amount + reference or narration), match_status (`unmatched` / `strong` / `probable` / `confirmed` / `ignored`), matched_pay_request_id, payment_id | A line backs at most one payment |
| advance_transactions | driver_id, agreement_id, kind (`deposit` / `adjustment` / `refund` / `reversal`), amount_paise (signed), payment_id, status (`pending` / `approved` / `rejected`), requested_by, approved_by, approved_at, reason | Balance = sum of approved rows, never below 0 |

## Escalations and alerts

| Table | Key columns | Notes |
| --- | --- | --- |
| escalations | driver_id, raised_by (owner), assigned_to (manager at raise time; follows reassignment), overdue_paise_at_raise, overdue_days_at_raise, note, follow_up_on, status (`open` / `in_progress` / `resolved` / `closed`), resolved_at, closed_by, closed_reason | One open or in-progress escalation per driver (partial unique) |
| escalation_events | escalation_id, actor_id, kind (`call` / `visit` / `promise` / `note` / `paid` / `reassigned` / `system`), promised_on, note, at | |
| alerts | kind, entity_type, entity_id, severity, message, created_at, resolved_at, resolved_by | Licence expiry, vehicle papers, overdue rent, approvals waiting, follow-ups due |

## Removed from earlier plans

`driver_credentials`, `payment_intents`, `support_requests`, `support_messages`, `faq_articles`, `profile_change_requests`, `gateway_events`, and every `/me` endpoint. Do not create them.

## Constraints to create (SQL sketch; adapt names in migrations)

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Rule 2: one active agreement per driver and per vehicle; no overlapping periods
CREATE UNIQUE INDEX one_active_agreement_per_driver  ON agreements (driver_id)  WHERE status = 'active';
CREATE UNIQUE INDEX one_active_agreement_per_vehicle ON agreements (vehicle_id) WHERE status = 'active';
ALTER TABLE agreements ADD CONSTRAINT no_driver_overlap
  EXCLUDE USING gist (driver_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
  WHERE (status IN ('active', 'ended'));
ALTER TABLE agreements ADD CONSTRAINT no_vehicle_overlap
  EXCLUDE USING gist (vehicle_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
  WHERE (status IN ('active', 'ended'));

-- Rule 1: exactly one charge per agreement per calendar day
ALTER TABLE rent_charges ADD CONSTRAINT one_charge_per_day UNIQUE (agreement_id, rent_date);

-- Money and allocation sources
ALTER TABLE payments            ADD CONSTRAINT payment_positive CHECK (amount_paise > 0);
ALTER TABLE payment_allocations ADD CONSTRAINT alloc_positive   CHECK (amount_paise > 0);
ALTER TABLE payment_allocations ADD CONSTRAINT one_source
  CHECK ((payment_id IS NULL) <> (advance_transaction_id IS NULL));

-- The same UPI reference cannot be recorded twice; a statement line backs one payment.
-- Rejected and reversed payments release their reference and statement line, so they can be re-recorded correctly.
CREATE UNIQUE INDEX unique_payment_reference ON payments (method, reference)
  WHERE reference IS NOT NULL AND status NOT IN ('rejected', 'reversed');
CREATE UNIQUE INDEX one_payment_per_statement_line ON payments (statement_line_id)
  WHERE statement_line_id IS NOT NULL AND status NOT IN ('rejected', 'reversed');

-- Rule 15: one open escalation per driver
CREATE UNIQUE INDEX one_open_escalation_per_driver ON escalations (driver_id)
  WHERE status IN ('open', 'in_progress');

-- Rule 11: audit log is insert-only for the app role
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM app_user;
```

Use two database roles: `app_owner`, which owns the schema and runs migrations, and `app_user`, which the app uses at runtime with only the grants it needs.

## Grants and insert-only tables (rule for every migration)

- Migration `0001` runs `ALTER DEFAULT PRIVILEGES` as `app_owner`, so every table `app_owner` creates later automatically gives `app_user` SELECT, INSERT, UPDATE and DELETE (never TRUNCATE), and every sequence USAGE and SELECT. A test creates a probe table and checks this.
- **Insert-only tables** are `audit_logs`, `settings_versions`, `rent_charges`, `kyc_events`, `escalation_events` and `document_access_log`. They are listed in `backend/app/core/db_grants.py` (`INSERT_ONLY_TABLES`). The migration that creates one must run `make_insert_only_sql("<table>")`, which revokes UPDATE, DELETE and TRUNCATE from `app_user`, right after creating it. A test checks every listed table as soon as it exists and fails if `app_user` can change or remove rows.
- **Audit entries are written in the same database transaction as the change they record** (`write_audit()` uses the caller's session and never commits). A rolled-back change leaves no audit entry; a test proves it.
