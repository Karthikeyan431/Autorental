# Week 4: Free government checks, and autos

**Goal:** add the free government verification methods (UIDAI Secure QR and the Parivahan lookup record) alongside manual review, and build auto management.

**Read first:** `docs/kyc.md` (identity methods a and b, licence method a), `docs/data-model.md` (autos, identity and licence details), `docs/business-rules.md` (rules 8, 2), `docs/open-questions.md` (N13, Q25, Q29).

## Build

**UIDAI app attestation (`uidai_app_attested`), on by default**
- A form for: name, date or year of birth, last 4 digits, "signature shown as valid in the UIDAI app" (yes or no), and an optional masked screenshot.
- UI label: "Checked by staff with the UIDAI app".

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

**Autos**
- `vehicles` (normalised registration number, unique), statuses, and guarded transitions (`rented` only via agreements, Week 5).
- `vehicle_compliance` with documents and expiry alerts (insurance, fitness, permit by default; Q29).
- `maintenance_records`; setting `maintenance` and back.
- UI: autos list and detail, papers, maintenance.

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

**Flag:** with the flag off, the endpoint returns 404; with it on, it works.

**Production guard:**
- the app refuses to start with `APP_ENV=production` and the demo method on;
- eligibility returns `SIMULATED_VERIFICATION` for simulated checks in production.

**Parivahan record:** a screenshot is required; validity dates feed eligibility.

**Autos:**
- a duplicate registration number is refused (after normalising spaces and case);
- an auto in `maintenance` or `inactive` cannot be selected for an agreement (checked again in Week 5);
- staff cannot set `rented` directly.

## Done when

- [ ] A driver can be approved using UIDAI app attestation plus a Parivahan lookup, with no paid service.
- [ ] The in-app QR path works in development with test payloads, and is off by default.
- [ ] Autos can be registered, with paper expiry alerts.
- [ ] `check.ps1` is green.

## You check

1. Approve a fake driver with the attestation form and a Parivahan-style record (made-up data, made-up screenshot).
2. Add 3 autos; give one an insurance date 10 days ahead: an alert appears.
3. Set `APP_ENV=production` with the demo method enabled: the app refuses to start.
