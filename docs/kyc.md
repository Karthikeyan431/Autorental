# Driver onboarding and KYC

Staff take each driver through these steps in one wizard. Identity and licence are separate checks (rule 7), each with attempts and history.

## Steps

1. **Register:** name, mobile, alternate mobile, address, date of birth, emergency contact. Mobile and licence numbers must be unique (normalise first). `created_by` and `managed_by` are set to the current staff member.
2. **Photo:** taken with the device camera (`getUserMedia`), with a file-upload fallback. Strip EXIF (Pillow), resize to at most 1600 px, store encrypted.
3. **Consent:** record purpose `kyc` (and `aadhaar_qr` if a QR check is used), the notice version, method, `captured_by` and time. No KYC step is allowed before consent; UIDAI says offline verification must not happen without explicit consent.
4. **Identity check:** one of the methods below.
5. **Licence check:** one of the methods below.
6. **Staff decision:** a checklist per check, then approve, reject (reason required), or ask for documents again. Staff can decide by default (N2); the owner can reopen.
7. **Eligibility** is recomputed. Drafts show what is still missing.

## Identity methods

### a) UIDAI Secure QR, in the app (`uidai_qr`) — behind the flag `AADHAAR_QR_INAPP_ENABLED` (default `false`, N13)

- The QR is on the Aadhaar letter, PVC card, e-Aadhaar and the mAadhaar app. UIDAI signs it digitally, and the signature is checked with UIDAI's published certificate. No call to UIDAI is needed.
- **Front end:** scan with `@zxing/browser` from the camera, and send the scanned text to the backend over HTTPS. Never store it in the browser.
- **Back end:** implement decoding and signature verification **exactly per UIDAI's "Secure QR Code" specification** (download it from uidai.gov.in; do not guess the byte layout). In outline:
  - the scanned value is a large decimal number; convert it to bytes and decompress;
  - fields are separated by a delimiter byte;
  - the signature covers the data part and is verified with UIDAI's certificate.
  The certificate file path comes from the environment (`UIDAI_CERT_PATH`).
- Show the staff member the photo and details from the QR, so they can confirm the person in front of them matches. Record `photo_match_confirmed_by`.
- **Store only:** name, date or year of birth, gender, the last 4 digits of the Aadhaar number, `qr_signature_valid`, time and checker. Never the full number, the raw QR, or the QR photo (unless the legal adviser says otherwise).
- **Tests:** use synthetic payloads in the spec's format, signed with a **test key pair** that the tests generate. In tests, point the verifier at the test certificate. Assert that a genuine payload passes and that any changed byte fails. Never use a real Aadhaar QR in tests or fixtures.

### b) UIDAI app, attested by staff (`uidai_app_attested`) — the default while N13 is open

- Staff scan the driver's QR with UIDAI's free **Aadhaar QR Scanner** app on their own phone and compare the result with the person.
- In our app they record: name, date or year of birth, last 4 digits, "signature shown as valid by the UIDAI app" (a yes or no attestation), and an optional screenshot with the number masked.
- The label in the UI is **"Checked by staff with the UIDAI app"**, never "Verified by system".

### c) Manual (`manual`)

- Staff upload a **masked Aadhaar** (front, and back if needed) or another accepted ID (N12). The checklist includes "Only the last 4 digits are visible".
- If the upload shows a full Aadhaar number, staff must reject it and ask for a masked copy. Never store the full-number image.

## Licence methods

### a) Parivahan lookup (`parivahan_lookup`)

- A button opens the official Parivahan licence-status page in a new tab. **Do not** automate, scrape or call that site from our server.
- Staff enter the licence number and date of birth there. In our form they record: licence status text, non-transport and transport validity dates, vehicle classes, issuing authority, the time of the lookup, and a screenshot upload.
- The licence number is stored encrypted, with a hash for duplicate checks.

### b) Manual (`manual`)

- Front and back uploads plus the same fields, typed from the card.

The driver can also show the licence in their own DigiLocker or mParivahan app as a cross-check. Record that as a checklist item; it is not a separate method.

## Statuses (per check, per attempt)

`draft → submitted → under_review → approved | rejected | resubmission_required`. An approved licence becomes `expired` (by a job) when its validity date passes. Only the owner can reopen an approved or rejected check. A reopen creates a new attempt with status `under_review`; the previous attempt stays in history with its status unchanged, and is no longer current.

## Eligibility (rule 10): the single function used by agreement activation

```python
def check_eligibility(driver, on_date) -> Eligibility:
    reasons = []
    identity = current_check(driver, "identity")
    licence = current_check(driver, "licence")
    if identity is None or identity.status != "approved": reasons.append("IDENTITY_NOT_APPROVED")
    if licence is None or licence.status != "approved":   reasons.append("LICENCE_NOT_APPROVED")
    elif licence.valid_until(on_date) < on_date:           reasons.append("LICENCE_EXPIRED")   # date used: Q22/N12
    if driver.account_status != "active":                  reasons.append("ACCOUNT_NOT_ACTIVE")
    if has_blocking_restriction(driver):                   reasons.append("BLOCKING_RESTRICTION")
    if has_active_agreement(driver):                       reasons.append("ALREADY_ASSIGNED")  # rule 2
    if settings.APP_ENV == "production" and (identity_is_simulated or licence_is_simulated):
        reasons.append("SIMULATED_VERIFICATION")
    return Eligibility(ok=not reasons, reasons=reasons)
```

`valid_until` uses the transport validity date when present, otherwise non-transport (Q22 default; confirm with the client).

## Alerts

- Licence expiring within `licence_alert_days` (30) and on the expiry date: alert the owner and the manager; no automatic action (Q23).
- Vehicle papers expiring within `vehicle_alert_days`.

## Documents (all KYC files, photos, screenshots, signed agreements, statements)

- Allowed types: JPEG, PNG and PDF; maximum 5 MB for images and 10 MB for PDFs; check the real file type, not the extension.
- Strip image EXIF. Store encrypted with AES-256-GCM (key from env, `key_id` recorded) outside the web root, with a random storage key and SHA-256 recorded.
- Serve only through `GET /documents/{id}/content` after a permission check. Stream the file, set `Cache-Control: no-store`, and log every view in `document_access_log`. Never use public URLs.
- Retention follows Q27 (default: keep until the owner decides); a purge job exists but is off.
