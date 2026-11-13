# Requirements (plan v2, zero-cost version)

Source: the client meeting on 12 November 2026 and the follow-up "no paid services" decision. Anything not here is out of scope until the client approves it.

## 1. What the client asked for

1. **Two roles only:** the owner (admin) and staff. Drivers get no login and no app.
2. **Up to 10 staff:** the owner creates, edits and deactivates staff accounts and controls what they can do.
3. **Staff onboard drivers:** they enter details, take the photo, collect and upload documents, and verify identity and licence.
4. **Two ways to verify:** manual document upload, and a government-verified source (free version: UIDAI Secure QR and the Parivahan licence portal).
5. **Ownership on every driver:** "Created by" and "Managed by" staff, with full history, visible to the owner.
6. **Payment rhythm per driver:** set by staff. Daily by default, or weekly (N3).
7. **Autopay:** asked for, but replaced by **daily one-tap UPI pay requests** because automatic debit always needs a paid gateway.
8. **Self-pay needs owner approval:** every payment counts only after the owner approves it.
9. **The owner monitors everything:** drivers, documents, autos, every payment, and every staff member's work.
10. **Escalation:** the owner escalates a missed payment to the managing staff member, who follows up with the driver.
11. **Quality:** reliable in daily use, with the best features for this business.
12. **Delivery:** built with Claude Code in one-week milestones.

Autos, agreements, the daily rent ledger and reports carry over from the original handoff.

## 2. The zero-cost substitutions

| Need | Free way we build |
| --- | --- |
| Automatic rent collection | A daily pay request: a UPI link and QR for the business UPI ID with the amount and a reference code. Staff send it on WhatsApp with one tap. |
| Confirming payments | The owner uploads the bank statement (CSV or Excel). The system matches credits to pay requests; the owner approves in bulk. |
| Identity check | UIDAI Secure QR: decode the QR and verify UIDAI's digital signature in the app (flag `AADHAAR_QR_INAPP_ENABLED`), or staff use UIDAI's free Aadhaar QR Scanner app and record the result (flag `AADHAAR_APP_ATTEST_ENABLED`). Both flags default to off until the legal adviser answers N13 (D47), and the in-app decoder is built only after that (D48); until then identity is checked by manual review of the masked Aadhaar. |
| Licence check | Staff look up the licence on the official Parivahan site and record the status, validity and vehicle classes with a screenshot. |
| Messages to drivers | WhatsApp click-to-chat links (`https://wa.me/91XXXXXXXXXX?text=...`); staff tap Send. |
| Alerts to owner and staff | In-app notifications and Web Push (VAPID). |
| Hosting | Oracle Cloud Always Free, Caddy with Let's Encrypt, and a free subdomain. |

**Out of scope:** the driver app or any driver login, payment gateways, UPI AutoPay, the DigiLocker API, paid KYC providers, SMS, the WhatsApp Business API, and paid hosting. The code keeps provider interfaces for payments and verification, so a paid option can be added later without a rebuild, but none is built now.

**UPI charge to keep in mind:** from 15 October 2026, UPI payments to a merchant above ₹2,000 carry a 0.4% charge; at or below ₹2,000 they are free. Daily rent stays free. Warn in the UI when a weekly pay request goes over ₹2,000 (N3).

## 3. Roles and permissions

Owner-only actions cannot be granted to staff. "Grantable" means the owner can switch the action on for a named staff member.

| Action | Owner | Staff by default | Grantable to staff |
| --- | --- | --- | --- |
| Create, edit, deactivate staff; set permissions | Yes | No | Never |
| Business settings: rent due time, business UPI ID and payee name, staff limit, WhatsApp template | Yes | No | Never |
| Register a driver, take the photo, record consent, upload documents | Yes | Yes | n/a |
| Verify identity and licence; approve, reject or ask again (N2). From Week 4: only for drivers they currently manage (N16) | Yes | Yes | n/a |
| Reopen or overturn a verification | Yes | No | Never |
| Change which staff member manages a driver | Yes | No | Never |
| Place or lift a blocking restriction; suspend or reactivate a driver (`drivers.restrict`) | Yes | No | Yes |
| Register autos, papers and maintenance | Yes | Yes | n/a |
| Create an agreement draft; print it | Yes | Yes | n/a |
| Activate or end an agreement (eligibility checked by the system) | Yes | Yes | n/a |
| Set a driver's payment rhythm; generate and send pay requests | Yes | Yes | n/a |
| Record a payment with proof; choose or confirm the days it covers | Yes | Yes | n/a |
| Upload a bank statement; confirm matches | Yes | No | Yes |
| Approve or reject a payment | Yes | No | Never |
| Request a reversal or a charge adjustment (`adjustments.request`) | Yes | Yes | n/a |
| Decide a reversal or adjustment (`adjustments.decide`); approve advance use or refunds | Yes | No | Never |
| Raise or close an escalation | Yes | No | Never |
| Work an escalation (log calls, visits, promises) | Yes | Their drivers | n/a |
| See drivers | All | All; edit only drivers they manage (N1) | n/a |
| See full identity values (licence number, address, dates of birth, gender; masked by default) via "Show", one audited reveal at a time (D45, from Week 4) | Yes | Only drivers they currently manage | Never (not even with `drivers.edit_any`) |
| View KYC document images (they show those values in full) (D45, N16, from Week 4) | Yes | Only drivers they currently manage | Never |
| Edit masked identity fields (address, date of birth; "Leave blank to keep the current value") (N17, from Week 4) | Yes | Only drivers they currently manage | Never (`drivers.edit_any` covers the other fields only) |
| Business-wide money figures, reports, Excel export | Yes | Own drivers only (N1) | Yes |
| Audit log | Yes | No | Never |

**Masked identity fields (client request, 13 Nov 2026; D45, from Week 4):** identity values
are masked on every screen and in every list, detail and KYC response, export, log and error
message. Full values come only from the reveal endpoint, for the owner and the driver's current
manager, one field at a time, rate-limited per user (setting `reveal_limit_per_hour`, 30), and
each reveal is audited and shown in the driver's Activity tab. The address and both dates of
birth are also encrypted at rest (N15). If a manager is away, the owner changes the manager. Aadhaar is unchanged: the last 4 digits only, and no field may hold a
full Aadhaar number.

**Staff limit:** the setting `staff_limit` starts at 10 active staff. Creating or reactivating staff beyond the limit is refused (N10).

## 4. Screens

1. **Sign in**, with a one-time code step for the owner (TOTP 2-step).
2. **Dashboard** (owner): today's rent expected and approved, payments awaiting approval (statement matches first), pay requests sent, paid and unpaid, last statement upload, missed rent with an Escalate button, open escalations by staff member and any past follow-up, KYC waiting, licences and vehicle papers expiring, autos available and rented.
3. **Dashboard** (staff): my drivers, my escalations, today's unpaid pay requests for my drivers, KYC I need to finish.
4. **Drivers list:** filters for status, managed by, KYC, overdue, and search.
5. **Driver page:**
   - **Header:** photo, name, code, status, "Created by" (name and date), "Managed by" (name and since when), payment rhythm, today's pay request.
   - **Tabs:** details, KYC and documents, agreement and auto, rent ledger, payments, escalations, activity timeline from the audit log.
6. **Register driver** wizard: details, photo, consent, identity, licence, review and staff decision.
7. **KYC queue:** pending, under review, resubmission needed, rejected, expiring.
8. **Autos:** list and detail, papers with expiry, maintenance.
9. **Agreements:** new agreement with a live eligibility check showing the reasons, print, signed copy, end.
10. **Pay requests today:** one row per driver with the amount, a Send on WhatsApp button, a QR button, and sent and paid states.
11. **Payments:** record payment, approval queue (bulk approve, reject with a reason), receipts, reversal requests.
12. **Bank statements:** upload, column mapping (saved per bank), matched, probable and unmatched lines, confirm and approve.
13. **Escalations:** owner board by staff member; staff "My escalations" with an event log.
14. **Reports:** the report keys in `api.md`, each with Excel export.
15. **Staff management**, **Settings** (versioned), and the **Audit log**.

**UI quality:**
- Responsive for desktop, tablet and phone; staff mostly use phones.
- Clear tables with search, filters and pagination.
- A confirmation step for every money or status action.
- Loading, empty, success and error states on every screen.
- Accessible forms with labels and error messages.
- Indian rupee formatting.
- Nothing flashy.
