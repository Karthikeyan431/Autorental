# Open client questions and the defaults we build

Build the default until the client answers. Make the default a setting or a flag where practical, so an answer is a small change. When an answer arrives, fill in the **Answer** column and tell Claude Code: "N3 is answered, see open-questions.md."

## New questions (plan v2)

| # | Question | Default we build | How it is built | Needed by | Answer |
| --- | --- | --- | --- | --- | --- |
| N11 | Who owns the free Oracle Cloud account and the subdomain? | The client's name, with CODE & CANVAS as administrator | Deployment docs | Week 1 | |
| N1 | Can staff see all drivers or only their own? Can they see business-wide money? | See all drivers, edit only their own; money figures for their own drivers only | Permissions `drivers.edit_any`, `reports.all` (off for staff) | Week 2 | |
| N10 | Is 10 staff a fixed limit or a starting number? | A setting that starts at 10 | `staff_limit` | Week 2 | |
| N2 | Can staff approve KYC alone, or must the owner also sign off? | Staff approve; the owner is alerted and can reopen | Permission `kyc.decide` (staff on); `kyc.reopen` owner-only | Week 3 | |
| N12 | Which ID documents besides masked Aadhaar, and which licence classes qualify? (old Q21, Q22) | Masked Aadhaar only; staff judge the class with the checklist; the transport validity date is used if present | Setting `accepted_id_types`, `permitted_licence_classes` | Week 3 | |
| N14 | Do most drivers have an Aadhaar card, e-Aadhaar or mAadhaar with the Secure QR? | Manual review for those who do not | All methods available | Week 3 | |
| N13 | Must the business register with UIDAI as an offline verification entity to scan Aadhaar QR? (legal adviser) | Staff use UIDAI's free app and attest; in-app scanning off | Flag `AADHAAR_QR_INAPP_ENABLED=false` | Week 4 | |
| N3 | Daily payments, or weekly for some drivers? (weekly above ₹2,000 to a merchant UPI ID carries 0.4%) | Per driver; daily by default; warning above ₹2,000. **Weekly = paying in arrears** for days already charged (Q16 stays); a weekly driver's charges are due on the first `weekly_pay_day` on or after the rent date, at the rent due time, so they are not overdue mid-week. *Agency default 12 Nov 2026; awaiting client confirmation.* | `drivers.payment_rhythm`, `weekly_pay_day`, `weekly_mdr_warning_paise`; `due_at` per charge | Week 5 | |
| N4 | At what time are each day's pay requests sent? | 08:00, before the due time | `pay_request_time` | Week 5 | |
| N5 | Which UPI ID receives rent? | The business bank's merchant UPI ID | `business_upi_id`, `upi_payee_name` | Week 5 | |
| N6 | Which payment methods are allowed? | UPI to the business and cash at the office | `payments.method` values | Week 6 | |
| N7 | Do statement-matched payments still need the owner's click? | Yes: one click for all strong matches | No auto-approve code path | Week 6 | |
| N8 | While a payment awaits approval, does the driver show as overdue? | Yes, flagged "payment awaiting approval" | Ledger view | Week 6 | |
| N9 | Suggest an escalation after how many days overdue? | 1 day; the owner decides | `escalation_suggest_after_days` | Week 6 | |

## Still open from the original brief

| # | Question | Default we build | Needed by | Answer |
| --- | --- | --- | --- | --- |
| Q28 | Does "active drivers" on the dashboard mean drivers with an auto, or all approved? | Show both, labelled | Week 2 | |
| Q30 | English only, or also a regional language? | English only, with text kept in one place for later translation | Week 1 | |
| Q23 | If a licence expires during an agreement? | Alert 30 days before and on expiry; no automatic action | Week 3 | |
| Q26 | What blocks a driver from a new auto? | Only blocks the owner places | Week 3 | |
| Q27 | How long are KYC documents kept after a driver leaves? | Kept until the owner decides; the purge job exists but is off | Week 3 | |
| Q25 | Does a passed QR check approve on its own? | No; staff still decide | Week 4 | |
| Q29 | Which vehicle papers need expiry alerts? | Insurance, fitness, permit | Week 4 | |
| Q1 | Can an auto go to a new driver on the day it is returned? | No; next day at the earliest | Week 5 | |
| Q2 | First day and a mid-day return? | Both charged in full | Week 5 | |
| Q3 | Grace period before overdue? | None; overdue at the due time | Week 5 | |
| Q9 | Is each day's rent due the same day or the next day? | Same day (`due_day_offset = 0`) | Week 5 | |
| Q10 | Can the daily rate change during an agreement? | No; a new rate needs a new agreement | Week 5 | |
| Q11 | Rent while the auto is off the road for repairs? | Charged; the owner may approve an adjustment | Week 5 | |
| Q12 | Late fees? | None | Week 5 | |
| Q13 | Agreement text and stamp paper? | Placeholder template; we write no legal terms | Week 5 | |
| Q4 | Can staff edit a recorded payment? | No edits; staff request a reversal, the owner decides | Week 6 | |
| Q5 | Advance refund rules? | Refunds off | Week 6 | |
| Q14 | What is "advance"? | A refundable deposit, amount set per agreement | Week 6 | |
| Q15 | Overpayment beyond the chosen days? | Stays as unallocated credit for staff to apply later | Week 6 | |
| Q16 | Pay ahead for future days? | No; the credit waits until the days accrue | Week 6 | |
| Q18 | GST invoices or simple receipts? | Simple receipts | Week 6 | |
| Q19 | Collection reports by date received or by rent day? | Both, labelled | Week 8 | |

Settled or dropped: Q6 (staff register drivers), Q7 (no SMS; WhatsApp links), Q8 and Q17 (no gateway), Q20 and Q32–Q37 (no driver app), Q21–Q22 (now N12), Q24 (now N2), Q31 (commercial, not code).

## Things to check early (record results here)

- Week 1: Python, Node, PostgreSQL versions on the development PC. Result (12 Nov 2026): Git 2.53.0, Python 3.12.10 (3.14.3 is the `py` default, not used), Node 24.15.0 (kept by decision) with npm 11.12.1, PostgreSQL 17.9 with the `postgresql-x64-17` service running, Claude Code 2.1.322, winget 1.29.380.
- Week 6: does the UPI link open with the client's merchant UPI ID in the 3 most-used UPI apps? Result:
- Week 7: a real statement export format from the client's bank (column names, date format). Use a **made-up sample file** in the same format for tests.
