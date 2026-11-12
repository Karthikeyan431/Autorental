# Week 7: Bank statement matching, escalations, alerts

**Goal:** owner approvals become fast through bank statement matching, missed rent is escalated to the managing staff member and tracked until it is cleared, and alerts reach people for free.

**Read first:** `docs/rent-and-payments.md` §4 and §8, `docs/data-model.md` (statements, escalations, notifications, push), `docs/business-rules.md` (rules 13, 14, 15), `docs/open-questions.md` (N7, N9).

## Build

**Bank statements**
- Upload CSV or XLSX (owner, or staff with `statements.upload`). The file is stored encrypted as a document; a duplicate file (same SHA-256) is refused.
- **Bank profiles:** a column-mapping UI (date, narration, reference, credit, debit, balance, date format, header row), saved per bank.
- **Parse:** credits only; amounts parsed with `Decimal` from text into paise; line fingerprints; already-imported lines skipped.
- **Matching:** strong, probable and unmatched, exactly as in §4. A match shows why it matched.
- **Review screen:**
  - **Confirm all strong** creates payments (source `pay_request`, the pay request's suggested days confirmed by the clicking user), which go straight into the owner approval queue.
  - Probable lines one by one.
  - Unmatched lines: link to a driver manually, or ignore with a reason.
- Never auto-approve (N7).
- Use a **made-up sample statement** in a common Indian net-banking CSV layout for tests and the demo.

**Escalations**
- **Missed-rent list:** overdue drivers with amount, oldest date and days overdue, and a "suggested" flag after `escalation_suggest_after_days` (N9).
- **Raise** (owner only): amounts filled automatically, note, follow-up date. Assigned to the current manager. One open escalation per driver.
- **Events** by the assigned staff member or the owner: call, visit, promise (with date), note, paid. The first staff event sets `in_progress`.
- **Auto-resolve** when the driver's overdue reaches 0 (checked on payment approval and by the jobs run). The owner can close with a reason.
- A "follow-up overdue" flag and alert when the follow-up date has passed.
- **Reassignment** (Week 3) moves open escalations and logs a `reassigned` event.
- **UI:**
  - owner board grouped by staff member, with filters;
  - escalation detail with a timeline;
  - staff "My escalations";
  - Escalate buttons on the dashboard missed-rent list and on the driver page.

**Alerts**
- In-app notifications (bell with count; mark read).
- **Web Push** via VAPID (`pywebpush`; keys in env; service worker in the frontend; subscribe and unsubscribe in the user menu). A failed push never breaks a request.
- **Alerts sent:**
  - to the staff member assigned an escalation;
  - follow-ups due today;
  - to the owner: payments awaiting approval at 18:00, a morning summary at 08:30, and licence and vehicle paper expiries.

## Out of scope

Reports and the final dashboards (Week 8).

## Tests to write first

- **Parsing:** `"1,20,000.50"` gives 12,000,050 paise; debit rows are ignored; dates parse per the profile format; a malformed row is reported, not crashed on.
- **Duplicates:** the same file twice is refused; overlapping statements skip already-imported lines (fingerprint).
- **Matching:**
  - reference code in the narration (with spaces or hyphens) plus equal amount gives strong;
  - equal amount within the date window and a unique driver gives probable;
  - two drivers fitting gives unmatched;
  - a statement line can back only one payment (DB constraint test).
- **N7:** after "Confirm all strong", the payments are `awaiting_approval`, never `approved`.
- **Escalations:**
  - only the owner can raise;
  - a second open escalation for the same driver is refused (DB);
  - assigned to the current manager;
  - reassigning the driver moves it;
  - approving the payments that clear the overdue auto-resolves it;
  - a partial payment does not;
  - the owner close needs a reason.
- **Suggested flag:** appears after N days overdue and not before.
- **Push:** a failing push endpoint is marked revoked after a 410 response and does not raise.

## Done when

- [ ] The owner uploads the sample statement, confirms the strong matches and approves them in 3 clicks.
- [ ] An escalation runs from raise to auto-resolve with the staff events on its timeline.
- [ ] `check.ps1` is green.

## You check

1. Upload the made-up sample statement, map its columns once, confirm the strong matches, and approve them.
2. Escalate a fake overdue driver. As the managing staff member on your phone, log a call and a promise. Approve a payment that clears it: it resolves.
3. Allow notifications in the browser and check that you get the escalation alert.
