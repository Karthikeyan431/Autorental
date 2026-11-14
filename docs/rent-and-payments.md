# Rent engine, pay requests, approvals and escalations

Rent is a ledger of daily charges. Payments are a separate list, and allocations link an **approved** payment to the specific days a person confirmed. Outstanding and overdue are always computed, never stored.

## 1. Daily accrual (rules 1 and 3)

- For each active agreement, the job creates one charge for every date from `start_date` to today (or `end_date`) that has none yet. There is no weekday or holiday logic, so Sundays and holidays are charged by construction.
- Each charge copies the agreement's `daily_rent_paise`. It also stores `due_at`, computed from the settings version in force when the charge is created: `rent_date + due_day_offset` at `rent_due_time`, in Asia/Kolkata, stored as UTC. Later settings changes affect only new charges.
- **Weekly drivers** (N3, awaiting client confirmation): weekly means paying in arrears for days already charged (Q16 stays). For a driver whose `payment_rhythm` is `weekly` when the charge is created, `due_at` is the first `weekly_pay_day` on or after `rent_date + due_day_offset`, at `rent_due_time`. So mid-week days are not overdue until the weekly pay day. Changing a driver's rhythm affects only charges created afterwards. Daily stays the default.
- The job is an idempotent CLI command (`python -m app.jobs.accrue`). In production it runs every 15 minutes from a systemd timer, and also on app start. The unique constraint makes re-runs harmless and fills days missed during downtime.
- The start day and end day both count as full days (Q2 default).

### Worked example (use it as a test)

Daily rent ₹300 from Monday 2 November 2026; due time 10:00 the same day. A ₹700 cash payment is recorded, its days are confirmed as 2 Nov ₹300, 3 Nov ₹300 and 4 Nov ₹100, and then it is approved. Position at 18:00 on Thursday 5 November:

| Rent date | Charge | Allocated | Balance | Status |
| --- | --- | --- | --- | --- |
| 2 Nov (Mon) | ₹300 | ₹300 | ₹0 | Paid |
| 3 Nov (Tue) | ₹300 | ₹300 | ₹0 | Paid |
| 4 Nov (Wed) | ₹300 | ₹100 | ₹200 | Part paid, overdue |
| 5 Nov (Thu) | ₹300 | ₹0 | ₹300 | Unpaid, overdue since 10:00 |
| **Total** | **₹1,200** | **₹700** | **₹500** | ₹500 outstanding, all overdue |

Before the owner approves the ₹700, outstanding is ₹1,200 and every day shows "payment awaiting approval" where a pending allocation covers it.

### Formulas

- **Day balance** = charge + approved adjustments − allocations that are not reversed and belong to an approved payment or approved advance transaction.
- **Outstanding** as of a date = sum of day balances up to that date.
- **Overdue** = sum of day balances whose `due_at` has passed (Q3: no grace period).
- **Awaiting approval** for a day = allocations on that day from payments with status `awaiting_approval` (shown, never subtracted).
- **Payment unallocated** = payment amount − its non-reversed allocations.
- **Advance balance** = sum of approved advance transactions (never below 0).

## 2. Pay requests (the free replacement for Autopay)

- **Settings:** `business_upi_id`, `upi_payee_name`, `whatsapp_template`. Each driver has a `payment_rhythm` (daily by default, or weekly, N3).
- **Generation:** an idempotent job and button. Each day at `pay_request_time` (setting, default 08:00, so drivers can pay before the due time; N4), or on `weekly_pay_day` for weekly drivers, the system creates one `pay_request` per driver per period with **amount = outstanding up to and including that period** (rule 18). Because future days never accrue (Q16), this is the outstanding on days already charged; for a weekly driver it is the past week's arrears plus any older balance. Do not create one for drivers without an active agreement. If an open request already exists for the driver, mark it `superseded` and create the new one, keeping a single open request per driver.
- **Reference code:** `R` + 4-digit driver number + `MMDD` of the period start, for example `R00421112`. Letters and digits only, because banks strip symbols from narrations.
- **UPI link:** `upi://pay?pa={business_upi_id}&pn={urlencoded payee name}&am={rupees with 2 decimals}&cu=INR&tn={reference_code}` (add `tr={reference_code}` if the bank's merchant UPI ID needs it). The QR encodes the same link (Python `qrcode` → PNG).
- **WhatsApp:** `https://wa.me/91{driver mobile}?text={urlencoded message}`. The default template is "Hello {name}, today's auto rent is ₹{amount}. Pay here: {upi_link} Ref {reference_code}. Thank you, {business_name}". Staff tap Send, WhatsApp opens on their phone, and they press Send. The app records `sent_by`, `sent_at` and `send_count` when the button is tapped.
- **Weekly warning:** if a request's amount is above ₹2,000 (setting `weekly_mdr_warning_paise`), show a warning that merchant UPI payments above ₹2,000 carry a 0.4% charge from 15 October 2026.
- **Week 1 or 6 check:** test that the link opens in the 3 most common UPI apps with the client's merchant UPI ID. If an app will not open the link, the QR still works. Record the result in `docs/open-questions.md`.

## 3. Recording a payment

- **From the bank statement** (section 4): a matched line creates a payment with `source = pay_request`, `method = upi`, `reference` = the bank reference, and `statement_line_id` set.
- **By staff:** cash at the office, or a UPI payment without the reference code. Staff enter the amount, method, UPI reference or UTR (required for UPI; duplicates refused), received date and a proof photo (UPI screenshot or cash slip).
- Every new payment starts as `awaiting_approval`. Staff confirm which days it covers (rule 4). The form pre-fills the suggestion from the pay request (oldest unpaid days first) and needs an explicit Confirm.
- **Idempotency:** the client sends an `idempotency_key` with each create, so a double tap creates one payment.

## 4. Bank statement import and matching

1. The owner, or staff granted `statements.upload`, uploads a CSV or XLSX from net banking. Refuse a file whose SHA-256 was already imported.
2. **Mapping:** the first time for a bank, map the columns (date, narration, reference, credit, debit, balance, date format, header row) and save it as a `bank_profile`.
3. **Parse:** keep credit rows only and convert amounts to paise exactly (parse text with `Decimal`, never `float`). Compute a line fingerprint; skip lines already imported.
4. **Match** each new line (never automatically approve):
   - **Strong:** the narration contains the `reference_code` of a pay request that is open **or was superseded in the last 7 days** (case-insensitive, ignoring spaces and symbols) **and** the amount equals that request's amount. This catches drivers who pay yesterday's link late.
   - **Probable:** the amount equals an open request amount, the date is within the request period start to +3 days, and exactly one driver fits. Show why.
   - Otherwise **unmatched**. Staff can link it manually to a driver.
5. **Review screen:** confirm strong matches in bulk. This creates payments with suggested days confirmed (rule 4, done by the person clicking). The suggested days are always **recomputed at confirm time** from the driver's oldest unpaid days, never taken from the matched request's stored `suggested_charge_ids`. Review probable matches one by one; unmatched lines can be ignored with a reason.
6. Statement lines never change money by themselves.

## 5. Owner approval (rule 13)

- **Queue:** statement-matched payments first, then the oldest. Filters by staff member, method and driver.
- **Approve:** works on one or many selected payments. In one transaction per payment:
  1. Lock the payment.
  2. Check that its confirmed allocations still fit each day's balance; re-lock the days in id order.
  3. Set `approved`.
  4. Issue the receipt number from the locked `receipt_counters` row.
  5. Write the audit entry.
  If a payment no longer fits, for example another payment was approved for the same day first, refuse that one with a clear reason and approve the rest.
- **Reject:** needs a reason, which staff see. Its allocations are marked reversed (`reversed_at`, `reversed_by`, `reversal_reason = 'payment rejected'`); nothing is deleted (rule 11). The pay request returns to `open` if it was linked. A rejected payment releases its UPI reference and statement line, so the money can be re-recorded correctly.
- **Receipt:** a PDF (reportlab) with business details, driver, amount, method, reference, days covered and receipt number. Staff can download it to share on WhatsApp.

## 6. Allocation transaction (rule 4)

All in one database transaction:
1. Lock the payment row (or the advance transaction).
2. Lock the agreement rows of the chosen days **in id order**, so two staff members cannot deadlock. (`rent_charges` is insert-only, so the app role cannot lock its rows; D53.)
3. Check that each day belongs to this driver's agreement, has already accrued (no future days, Q16), and that each amount fits the day's balance *including other pending allocations*, and the total fits the payment's unallocated amount.
4. Write the allocations and the audit entry, then commit.

Any amount staff do not allocate stays as unallocated credit on that payment until they do (Q15). It is never spread across days automatically.

## 7. Corrections and advance (rules 5 and 11)

- Nothing financial is edited or deleted. A wrong allocation is **reversed**, which restores the day's balance.
- A wrong approved payment gets a **reversal**: staff request it, the owner decides (Q4). Its allocations are reversed and its receipt is marked cancelled.
- A wrong charge, such as a mistyped rate, gets an owner-approved **charge adjustment** with a reason; the original charge stays.
- **A return recorded late** (D52): the return date may be in the past. Every charge already created after it stays, and each gets a pending waiver of its full net charge ("Returned on <date>, recorded late") for the owner to decide.
- **Advance:** a deposit is a payment with purpose `advance_deposit` (it also needs approval). Using advance against rent means staff propose the amount and days, and nothing changes until the owner approves. A setting can switch adjustments off. Refunds stay off until Q5 is answered.

## 8. Overdue and escalation (rule 15)

- A day is overdue when its balance is above 0 and `now > due_at`.
- **Missed-rent list:** drivers with overdue above 0, with amount, oldest overdue date and days overdue. An escalation is suggested after `escalation_suggest_after_days` (default 1, N9); the owner still decides.
- **Raise:** owner only. The amount and days overdue fill in automatically; the owner adds a note and a follow-up date. The escalation is assigned to the driver's current manager. Only one open escalation is allowed per driver.
- **Work:** the assigned staff member (or the owner) logs events: call, visit, promise (with a promised date), note, paid. The first staff event moves it to `in_progress`.
- **Resolve:** automatic when the driver's overdue reaches 0, through approved payments. The owner can also close it with a reason.
- **Follow-up overdue:** the follow-up date has passed and the escalation is not resolved. It is flagged on the owner dashboard and alerted.
- **Reassignment:** when the owner changes a driver's manager, open escalations move to the new manager and a `reassigned` event is logged.
- **Notifications:** on raise, the assigned staff member gets an in-app and Web Push alert. Each morning the owner gets a summary: approvals waiting, follow-ups due, escalations past date.
