# Decisions log

Decisions made with the agency lead. Client-facing rule changes still need the client's written approval (see `business-rules.md`); items marked *awaiting client* are agency defaults until then.

## 12 November 2026 (before Week 1)

| # | Decision | Docs updated |
| --- | --- | --- |
| D1 | **Seed by week.** Week 1 seeds only the first settings version. Week 2 adds the owner and 2 staff with a dev-only password from `SEED_DEV_PASSWORD`. Week 3 adds drivers and Week 4 autos. The seed refuses to run when `APP_ENV=production`. | week-01 to week-04 |
| D2 | **Dependencies approved:** pydantic-settings, psycopg 3 (binary), uvicorn, httpx, python-multipart, pip-audit, APScheduler (development scheduling only), ESLint, Prettier. All must be free and open source and listed in `dependencies.md`. `check.ps1` runs ruff, mypy, pytest, pip-audit, eslint, tsc, vitest and npm audit. | CLAUDE.md, dependencies.md |
| D3 | **No server work until Week 8.** The client creates the Oracle account early, outside the code. | START_HERE.md |
| D4 | **KYC reopen** creates a new attempt in `under_review`. | business-rules (rule 12), kyc.md, week-03 |
| D5 | `unique_payment_reference` and `one_payment_per_statement_line` exclude both `rejected` and `reversed` payments. | data-model.md, rent-and-payments §5, week-06 |
| D6 | **Rejecting a payment** marks its allocations reversed with the reason "payment rejected". Allocations are never deleted. | business-rules (rule 11), data-model.md, rent-and-payments §5, week-06 |
| D7 | **Weekly rhythm** means paying in arrears for days already charged (Q16 stays). A weekly driver's charge is due on the first `weekly_pay_day` on or after the rent date, at the rent due time. Daily stays the default. *Awaiting client (N3).* | business-rules (rule 3), open-questions N3, rent-and-payments §1–2, data-model, week-05 |
| D8 | **Strong matching** also checks requests superseded in the last 7 days. Suggested days are always recomputed from the driver's oldest unpaid days at confirm time. | business-rules (rule 4), rent-and-payments §4, week-07 |
| D9 | **Permissions.** `drivers.restrict` covers suspend, reactivate and restrictions (owner by default, grantable). New codes: `adjustments.request` (staff on by default) and `adjustments.decide` (owner only, never grantable). | api.md, requirements §3, week-02, week-05 |
| D10 | **Ending an agreement** sets the vehicle to `available` at once. The `[]` exclusion constraint and the eligibility check enforce Q1, and the UI shows "available from <date>". | data-model.md, week-05 |
| D11 | `demo` is a dev-only method. No `updated_at` on insert-only tables. `week-01.md` uses `py -3.12`. | data-model.md, week-01 |
