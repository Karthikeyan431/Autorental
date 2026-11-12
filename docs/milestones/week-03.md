# Week 3: Drivers, ownership, documents and manual KYC

**Goal:** staff can fully onboard a driver by document review: details, photo, consent, identity and licence, decision and eligibility. Every driver shows who created it and who manages it.

**Read first:** `docs/kyc.md`, `docs/data-model.md` (drivers and KYC), `docs/business-rules.md` (rules 6, 7, 9, 10, 12, 14), `docs/security.md` (data protection), `docs/open-questions.md` (N1, N2, N12, N14, Q23, Q26, Q27).

## Build

**Backend**
- `drivers` (driver code generator: D0001…), with `created_by` immutable and `managed_by`; `driver_manager_history`; owner-only reassignment with a reason; `driver_restrictions`; suspend and reactivate.
- Normalisation and uniqueness for mobile (+91) and licence number (store a hash for uniqueness, encrypt the value).
- **Documents service:**
  - check the real file type and size;
  - strip EXIF;
  - AES-256-GCM encryption to disk with `key_id`;
  - SHA-256;
  - streamed, permission-checked download with `Cache-Control: no-store`;
  - `document_access_log`.
- Driver photo upload (camera or file).
- Consents (purpose, notice version, method, `captured_by`), required before any KYC attempt.
- `kyc_checks` attempts and `kyc_events`; the manual method for identity (masked Aadhaar checklist) and licence (front and back plus typed details).
- Staff decision with a checklist: approve, reject (reason required) or resubmit. Owner-only reopen, which creates a new attempt.
- **Eligibility:** `check_eligibility()` exactly as in `kyc.md`, and `GET /drivers/{id}/eligibility`.
- **KYC queue** endpoint with filters.
- A licence expiry job that marks approved licences `expired` and creates alerts at 30 days and on expiry (Q23).
- Audit entries for all of the above, and for every document view.

**Frontend**
- **Drivers list** with filters, including "managed by me".
- **Driver page** with the header (photo, Created by, Managed by), tabs (details, KYC and documents, activity timeline), and owner-only "Change manager".
- **Register driver** wizard: details, photo (camera with file fallback), consent, identity (manual), licence (manual), review and decision. It saves a draft at each step.
- **KYC queue** and a review screen showing documents side by side with the checklist.

## Out of scope

UIDAI QR, Parivahan lookup (Week 4), agreements and money.

## Tests to write first

- `created_by` cannot be changed through the API, and a direct SQL update is refused by a trigger or guard.
- Staff cannot reassign a manager (403). An owner reassignment writes history and an audit entry.
- Staff can edit only drivers they manage (N1 default); the owner can edit all.
- A KYC attempt without consent is refused (`CONSENT_REQUIRED`).
- Approving identity leaves the licence unapproved (rule 7); history keeps every attempt and event.
- Staff can decide (`kyc.decide`); staff cannot reopen; the owner reopen creates attempt 2.
- Eligibility: each condition failing alone returns its reason; all passing returns ok. A licence valid until yesterday gives `LICENCE_EXPIRED`; valid until today is ok.
- A duplicate mobile or licence number is refused.
- Documents:
  - no access without login (401);
  - staff without permission get 404;
  - every view is logged;
  - the stored file is not readable without the key;
  - EXIF is removed;
  - a `.exe` renamed to `.jpg` is refused.
- No full 12-digit Aadhaar-like number is accepted in any identity field (validator test).

## Done when

- [ ] A driver can go from registration to "eligible" by manual review, on a phone screen.
- [ ] The driver page shows Created by and Managed by, with history.
- [ ] All tests pass; `check.ps1` is green.

## You check

1. On your phone, register a fake driver with a camera photo, masked-ID images (made-up) and a made-up licence; approve both checks.
2. As the owner, change the manager, then open the activity tab: the change is listed.
3. Try to view a document while signed out: it fails.
