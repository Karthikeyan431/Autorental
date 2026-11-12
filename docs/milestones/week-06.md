# Week 6: Pay requests, payments, owner approval, receipts

**Goal:** the free replacement for Autopay. Daily one-tap UPI pay requests sent on WhatsApp, staff-recorded payments with proof, the owner's approval queue, allocation to days, gapless receipts, reversals and advance.

**Read first:** `docs/rent-and-payments.md` §2, §3, §5, §6, §7, `docs/data-model.md` (pay requests, payments, receipts, advance), `docs/business-rules.md` (rules 4, 5, 11, 13, 18), `docs/open-questions.md` (N3–N8, Q4, Q5, Q14–Q16, Q18).

## Build

**Pay requests**
- Settings: `business_upi_id`, `upi_payee_name`, `whatsapp_template`, `pay_request_time` (08:00), `weekly_pay_day`; `drivers.payment_rhythm`.
- **Generation** (job and button), idempotent:
  - one open request per driver per period;
  - amount = outstanding up to that period (rule 18);
  - reference code `R` + 4-digit driver number + `MMDD`;
  - the previous open request is marked `superseded`.
- UPI link and QR PNG (Python `qrcode`). WhatsApp click-to-chat URL from the template. "Sent" tracking (`sent_by`, `sent_at`, `send_count`).
- A warning when an amount is above ₹2,000 (`weekly_mdr_warning_paise`).
- UI **Pay requests today:** rows per driver (filter "my drivers"), amount, a **Send on WhatsApp** button that opens `wa.me` and marks it sent, a **Show QR** button (full screen, for drivers paying at the office), and sent and paid state.

**Payments**
- Staff entry for UPI direct or cash: amount, reference (required for UPI, unique), received date, proof photo, `idempotency_key`.
- **Confirm days:** pre-filled from the open pay request (oldest unpaid first). It needs an explicit Confirm (rule 4) and uses the allocation transaction from §6, checking pending allocations too.
- **Owner approval queue:**
  - approve one or many: per payment, lock it, re-check that it fits, set approved, issue the receipt number, write the audit entry;
  - reject with a reason, which marks its allocations reversed ("payment rejected", never deleted) and returns a linked pay request to `open`.
  - Payments that no longer fit are refused one by one with a reason; the rest are approved.
- **Receipts:** a `receipt_counters` row lock per financial year (`RCPT/2026-27/000123`) and a PDF with the days covered. Downloadable for WhatsApp sharing.
- **Reversals:** staff request, owner decides; allocations are reversed, and the receipt is marked cancelled (Q4).
- **Advance:** deposits as payments with purpose `advance_deposit` (need approval). Using advance needs owner approval and is switched by a setting. Refunds are off (Q5). The balance is never below 0.

**Ledger and dashboard**
- Days with pending allocations show "payment awaiting approval" but stay unpaid and overdue (N8).
- Owner dashboard: payments awaiting approval (count and amount); pay requests sent, paid and unpaid today.

## Out of scope

Bank statement import and matching (Week 7), escalations (Week 7).

## Tests to write first

- **Generation:**
  - idempotent (running twice gives one open request per driver);
  - a driver without an active agreement gets none;
  - the amount equals outstanding up to the period;
  - a new period supersedes the old request;
  - the reference code format is right.
- **UPI link:** URL-encodes the payee name and note; the amount has 2 decimals from paise without floats (30000 gives `300.00`).
- **WhatsApp URL:** encodes the message; mobile in `91XXXXXXXXXX` form.
- **Payments:**
  - a duplicate UPI reference is refused; after the first payment is rejected or reversed, the same reference can be recorded again;
  - a double submit with the same `idempotency_key` creates one payment.
- **Rule 4:** creating a payment creates **no** allocation until Confirm; allocating to another driver's day, a future day, beyond a day's balance or beyond the unallocated amount is refused.
- **Rule 13:**
  - an unapproved payment never reduces outstanding or overdue;
  - after approval it does;
  - a rejected one never does, and its allocations are marked reversed with "payment rejected", not deleted;
  - the receipt number is issued at approval and only then.
- **Receipts:** approving 50 payments at once gives 50 unique receipt numbers with no gaps.
- **Concurrency:** two approvals that together over-fill the same day; one succeeds and the other is refused with a reason.
- **Reversal:** restores day balances, cancels the receipt, and writes an audit entry; staff cannot decide a reversal.
- **Advance:** a pending adjustment changes nothing; an adjustment above the balance is refused; the balance never goes below 0; refunds are refused while switched off.

## Done when

- [ ] Staff can send a day's pay requests from a phone in under a minute for 10 drivers.
- [ ] A payment is recorded, its days confirmed, approved by the owner, and the receipt PDF downloaded.
- [ ] All tests pass; `check.ps1` is green.

## You check

1. Set a test UPI ID in Settings. On your phone, tap **Send on WhatsApp** for a fake driver (use your own number as the driver's mobile) and check the message and link. **Do not pay real money to a test UPI ID.**
2. Scan the QR with a UPI app up to the confirm screen to check the payee and amount, then cancel.
3. Record a cash payment, confirm the days, approve it as the owner, and open the receipt.
4. Write the UPI-app link test result into `docs/open-questions.md`.
