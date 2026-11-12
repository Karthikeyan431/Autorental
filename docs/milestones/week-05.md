# Week 5: Agreements and the daily rent engine

**Goal:** assign autos through agreements that the database itself protects, and build a correct daily rent ledger with outstanding and overdue.

**Read first:** `docs/rent-and-payments.md` §1, `docs/data-model.md` (agreements and rent, constraint SQL), `docs/kyc.md` (eligibility), `docs/business-rules.md` (rules 1, 2, 3, 6, 10), `docs/open-questions.md` (Q1, Q2, Q3, Q9, Q10, Q11, Q12, Q13).

## Build

**Agreements**
- Draft, activate, end and cancel. Agreement number generator.
- `daily_rent_paise` fixed per agreement (Q10). `advance_required_paise` is stored (used in Week 6).
- **Activation in one transaction:**
  1. Lock the driver and the vehicle rows.
  2. Run `check_eligibility()`.
  3. Check the vehicle is `available`.
  4. Set the agreement `active` and the vehicle `rented`.
  5. Write the audit entry.
  Refuse with all the reason codes.
- **End:** set the end date (the return day is charged in full, Q2). The vehicle becomes `available` from the next day (Q1).
- All constraints from `data-model.md`: partial unique indexes and exclusion constraints.
- Printable agreement PDF (reportlab) from a **placeholder template** with business details, driver, auto, rate and dates. We write no legal terms (Q13). Upload of the signed copy.

**Rent engine**
- `rent_charges`, with the accrual CLI `python -m app.jobs.accrue`. It is idempotent, catches up missed days, and snapshots `due_at` and `settings_version_id`.
- In development, run it with APScheduler or by hand. The production timer comes in Week 8.
- Ledger queries for day balance, outstanding and overdue per the formulas, as SQL views or service queries (no stored totals).
- Charge adjustments: staff request, owner decides; only approved ones count (Q11).
- `GET /drivers/{id}/ledger` and `GET /rent/overdue` (the missed-rent list data).

**Frontend**
- **New agreement:** pick an eligible driver and an available auto; a live eligibility panel shows the reasons; rate and dates; confirm.
- Agreement detail with print and signed-copy upload; end agreement.
- **Ledger tab** on the driver page: day rows with charge, allocated, balance and status (Paid, Part paid, Unpaid, Overdue); totals; date filter.
- Owner dashboard cards: rent expected today, overdue drivers and amount.

## Out of scope

Recording payments, pay requests and approvals (Week 6). Until then, allocations are empty in this week's tests except the worked example, which inserts approved test payments directly.

## Tests to write first

- 4 days at ₹300 including a Sunday gives 4 charges and ₹1,200 (120,000 paise); a public holiday is charged.
- 1–30 November 2026 gives 30 charges; February 2028 gives 29.
- Running accrual twice gives no duplicates; after 3 days of "downtime", one run fills all 3 days.
- Changing the due time today keeps existing charges' `due_at`; tomorrow's charge uses the new time.
- An ended agreement gets no charges after its end date.
- Activation is refused for each eligibility reason, and for a vehicle in `maintenance`, `inactive` or `rented`.
- A second active agreement for the same driver or vehicle inserted **directly in SQL** raises a DB error; overlapping date ranges raise a DB error.
- Two staff activating the same vehicle for different drivers at the same moment: exactly one succeeds (concurrency test with two connections).
- The worked example in `rent-and-payments.md` §1 reproduces exactly (balances ₹0, ₹0, ₹200, ₹300; ₹500 overdue at 18:00 on 5 November).
- An approved adjustment of −₹300 waives a day; a pending one changes nothing.

## Done when

- [ ] A fake driver can be given an auto, and the ledger fills day by day.
- [ ] All rent tests pass; the database refuses a second active agreement.
- [ ] `check.ps1` is green.

## You check

1. Activate an agreement starting 3 days ago, run accrual, and see 4 charges (3 days ago to today).
2. Try to give the same auto to a second driver: refused, with the reason shown.
3. End the agreement and check that no charge appears for tomorrow.
