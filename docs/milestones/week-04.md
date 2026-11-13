# Week 4: Free government checks, and autos

**Goal:** add the free government verification methods (UIDAI Secure QR and the Parivahan lookup record) alongside manual review, and build auto management. Both Aadhaar methods are built behind flags that are **off by default** until the legal adviser answers N13 (D47); meanwhile identity is checked by manual review of the masked Aadhaar and the licence by the Parivahan lookup record.

**Read first:** `docs/kyc.md` (identity methods a and b, licence method a), `docs/data-model.md` (autos, identity and licence details), `docs/business-rules.md` (rules 8, 2), `docs/open-questions.md` (N13, Q25, Q29, N15 to N19), `docs/decisions.md` (D45 to D47), `docs/requirements.md` section 3 (masked identity fields).

## Build

**UIDAI app attestation (`uidai_app_attested`), behind `AADHAAR_APP_ATTEST_ENABLED=false` (D47)**
- A form for: name, date or year of birth, last 4 digits, "signature shown as valid in the UIDAI app" (yes or no), and an optional masked screenshot.
- UI label: "Checked by staff with the UIDAI app".
- Built the same way as in-app scanning: the flag is read at startup (add it to `config.py` and `.env.example`, default `false`); when it is off, the endpoint returns 404 and the UI hides the option. Until N13 is answered, identity is checked by manual review of the masked Aadhaar and the licence by the Parivahan lookup record.
- `uidai_app_attested` is added to the N13 question for the legal adviser (D47); do not turn the flag on in production until N13 is answered.

**UIDAI Secure QR in the app (`uidai_qr`), behind `AADHAAR_QR_INAPP_ENABLED=false`**
- **Back end:**
  - Decoder and RSA signature verifier implemented strictly from UIDAI's Secure QR Code specification. **Before writing the decoder, ask me to download the spec PDF and the UIDAI certificate from uidai.gov.in and put them in `docs/vendor/`; do not guess the format.**
  - The certificate path comes from `UIDAI_CERT_PATH`.
  - Return the extracted name, date or year of birth, gender, last 4 digits and the photo (in memory only) for the staff match.
  - Store only the allowed fields (see `kyc.md`).
- **Front end:** camera scanning with `@zxing/browser`; a staff match screen with the photo; a "Photo matches the person" confirmation.
- The flag is read at startup; when it is off, the endpoint returns 404 and the UI hides the option.

**Parivahan lookup record (`parivahan_lookup`)**
- An "Open Parivahan" button (new tab, official site).
- A form for the status text, non-transport and transport validity, vehicle classes, issuing authority and lookup time, plus a required screenshot upload.
- No automated calls to the site.

**Demo method (`demo`)**
- Available only when `APP_ENV` is `development` or `test`. Its results show a "DEMO – not real" badge everywhere.
- The app refuses to start in production if a demo method is enabled or any current check is `is_simulated`.

**Masked identity fields (client request, 13 Nov 2026; D45)**
- **Masked by default** on every driver screen and in every list, detail and KYC response:
  the licence number (shown as `•••• 1234`, from the stored last 4), the driver's address and
  date of birth, the date of birth on the licence, the date or year of birth on the identity
  document, and gender (N15 lists the fields; names and mobile numbers stay visible).
- **Reveal endpoint:** `POST /drivers/{id}/reveal` with `{"field": "<name>"}` returns the full
  value for that one view, with `Cache-Control: no-store`. POST, so the value never sits in a
  URL, browser history or the access log. Allowed for the owner and the driver's **current**
  manager only (checked at request time, so an old manager is refused straight after a
  manager change); any other staff member gets 403 `REVEAL_NOT_ALLOWED`; an unknown driver or
  field gets 404. Rate limit per user (N18): 429 `REVEAL_RATE_LIMITED`.
- **Audit:** each reveal writes exactly one entry `driver.field_revealed` (actor, driver, field
  name, time; never the value) in the same transaction, and it appears in the driver's
  Activity tab.
- **Never elsewhere:** full values never appear in list or detail responses, error messages,
  logs or exports (Week 8 Excel exports use the masked form).
- **UI:** a "Show" button next to each masked value, only for the owner and the current
  manager. The value is held in component state for that view only (not in the TanStack
  Query cache, not in storage) and hidden again on leaving the screen.
- **Editing (N17):** only the owner and the current manager can edit the masked fields; the
  form does not pre-fill them and says "Leave blank to keep the current value" (they can press
  "Show", audited, first). Staff with `drivers.edit_any` can edit the other fields only; a
  masked field in their request is refused with 403 `FIELD_NOT_EDITABLE`.
- **Documents and KYC decisions (N16, D33 as amended):** opening KYC document images and
  deciding (approve, reject, ask for documents again) follow the reveal rule: the owner and the
  current manager only. Others get 404 for document content (as before) and 403
  `KYC_DECIDE_NOT_ALLOWED` for a decision; their KYC queue shows only drivers they manage. If a
  manager is away, the owner changes the manager.
- **Error codes (D46, D47):** keep the names `KYC_DECIDE_NOT_ALLOWED` and `FIELD_NOT_EDITABLE`
  (both 403); add them to the error table in `docs/api.md` with `REVEAL_NOT_ALLOWED` and
  `REVEAL_RATE_LIMITED`.
- **Aadhaar unchanged:** last 4 digits only; no field may hold a full Aadhaar number (the
  existing `NoAadhaarStr` checks stay on every free-text field). A document image showing a
  full number is refused at review (required checklist item, D41); there is no automatic
  image check (N19).
- **Storage (N15):** encrypt `drivers.address`, `drivers.date_of_birth` and
  `licence_details.date_of_birth` at rest the same way as the licence number (AES-256-GCM field
  cipher, key id stored, context bound to table, column and row). A new migration converts the
  columns to encrypted text (only test data exists; never edit migration 0003). Dates are
  stored as ISO text before encryption. Any check that needs a date of birth (age at
  registration, the licence holder's age) decrypts it in the service layer, never in SQL.
  Update `data-model.md`. The identity document's date or year of birth and gender are masked
  in responses but stay as they are stored (N15 covers only address and the two dates of
  birth).

**Autos**
- `vehicles` (normalised registration number, unique), statuses, and guarded transitions (`rented` only via agreements, Week 5).
- `vehicle_compliance` with documents and expiry alerts (insurance, fitness, permit by default; Q29).
- `maintenance_records`; setting `maintenance` and back.
- UI: autos list and detail, papers, maintenance.
- **Seed:** add 5 fake autos (obviously fake registration numbers).

## Out of scope

Agreements, rent and payments.

## Tests to write first

**Secure QR verifier**, with synthetic payloads in the spec format signed by a test key generated in the test:
- a genuine payload passes;
- changing any single byte fails;
- the wrong certificate fails;
- a truncated payload fails cleanly (no crash);
- the stored record never contains more than the allowed fields (assert on the database row).
- No real Aadhaar QR in fixtures (a test scans fixtures for 12-digit numbers).

**Flags:** for each of `AADHAAR_QR_INAPP_ENABLED` and `AADHAAR_APP_ATTEST_ENABLED`: both default to `false`; with the flag off, its endpoint returns 404 and the UI hides the option; with it on, it works. With both off, a driver can still be approved by manual review plus the Parivahan lookup.

**Production guard:**
- the app refuses to start with `APP_ENV=production` and the demo method on;
- eligibility returns `SIMULATED_VERIFICATION` for simulated checks in production.

**Parivahan record:** a screenshot is required; validity dates feed eligibility.

**Masked identity fields:**
- the owner and the current manager can reveal each masked field;
- another staff member gets 403 `REVEAL_NOT_ALLOWED`, including staff with `drivers.edit_any`;
- after a manager change, the old manager is refused and the new one is allowed;
- list, detail, KYC and error responses never contain a full value (search every response body
  for the fake values);
- each reveal writes exactly one `driver.field_revealed` audit entry with the field name and
  no value, and it shows in the driver's Activity tab;
- captured logs (formatted as the API writes them) never contain the values, on success,
  refusal and rate limiting;
- the per-user rate limit returns 429 after the limit and writes no audit entry for refused
  reveals beyond one `driver.reveal_rate_limited` entry per window;
- document content and KYC decisions follow the same rule (owner and current manager only):
  staff with `drivers.edit_any` get 404 for document content and 403 for a decision; after a
  manager change the old manager is refused and the new one is allowed;
- only the owner and the current manager can edit masked fields; `drivers.edit_any` staff can
  edit the other fields and get 403 `FIELD_NOT_EDITABLE` for a masked one; a blank masked
  field keeps the current value;
- the database row holds ciphertext for the address and both dates of birth (assert on the raw
  row: the plain value is not in it), and the age check still works;
- the rate limit is the setting `reveal_limit_per_hour` (default 30).
- Frontend: values are masked by default; "Show" appears only for the owner and the current
  manager; the revealed value disappears after leaving the screen.

**Autos:**
- a duplicate registration number is refused (after normalising spaces and case);
- an auto in `maintenance` or `inactive` cannot be selected for an agreement (checked again in Week 5);
- staff cannot set `rented` directly.

## Done when

- [ ] A driver can be approved by manual review of the masked Aadhaar plus a Parivahan lookup, with no paid service.
- [ ] The in-app QR path works in development with test payloads, and is off by default.
- [ ] UIDAI app attestation works in development with its flag on, and is off by default.
- [ ] Autos can be registered, with paper expiry alerts.
- [ ] Identity fields are masked by default; only the owner and the current manager can reveal
      them, and each reveal is in the driver's Activity tab.
- [ ] `check.ps1` is green.

## You check

1. With the default flags, approve a fake driver by manual review of a made-up masked Aadhaar and a Parivahan-style record (made-up data, made-up screenshot); the UIDAI options are hidden. Then set `AADHAAR_APP_ATTEST_ENABLED=true` in development, restart, and approve another with the attestation form.
2. Add 3 autos; give one an insurance date 10 days ahead: an alert appears.
3. Set `APP_ENV=production` with the demo method enabled: the app refuses to start.
4. As a staff member who does not manage a driver, open that driver: address, date of birth
   and licence number are masked and there is no "Show". As the manager, press "Show" on the
   address, then open the Activity tab: the reveal is listed (without the value).
