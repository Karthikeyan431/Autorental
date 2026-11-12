# Week 8: Dashboards, reports, hardening, free deployment, handover

**Goal:** the owner sees everything at a glance; reports and Excel exports match the ledger; the app is hardened, deployed on free hosting with tested backups, and handed over with a user guide.

**Read first:** `docs/requirements.md` §4, `docs/api.md` (Dashboard, Reports, Audit), `docs/security.md`, `docs/deployment.md`, `docs/open-questions.md` (Q19, Q28).

## Build

**Dashboards**
- **Owner:** today's rent expected and approved; awaiting approval; pay requests sent, paid and unpaid; last statement upload; missed rent with Escalate; escalations by staff member and any past follow-up; KYC waiting; licences and papers expiring; autos available and rented; active drivers shown both ways (Q28).
- **Staff:** my drivers, my escalations, my unpaid pay requests today, my KYC to finish.
- **Staff performance** (owner): drivers managed, overdue amount, escalations open and closed, average days to clear.

**Reports and audit**
- All report keys in `api.md`, each with filters and Excel export (openpyxl, rupee formatting, frozen header, totals row).
- Collection reports by date received **and** by rent day (Q19).
- Staff see only their own drivers' figures unless granted `reports.all` (N1).
- **Audit log viewer** (owner): filters and a "Verify chain" button.

**Hardening**
- Go through OWASP ASVS level 1 and record pass or fix for each item in `docs/security-review.md`.
- Security headers and CSP, rate limits, `pip-audit` and `npm audit` clean (or justified).
- Playwright end-to-end tests (free) for 3 flows:
  1. Onboard a driver, activate an agreement, accrue, send a pay request, match the statement and approve.
  2. Overdue, escalate, staff events, resolve.
  3. Owner deactivates staff; staff are signed out at once.

**Deployment (free)**
- `deploy/`:
  - Caddyfile;
  - systemd units (`arms-api`, `arms-jobs.timer` every 15 minutes, `arms-backup.timer` nightly);
  - `deploy.sh`;
  - backup script (`pg_dump` plus files, `age` encryption, `rclone` to Oracle Object Storage, keep 14);
  - `MOVE.md`.
- With me at the keyboard: set up the Oracle Always Free VM (Ubuntu 24.04 arm64), PostgreSQL 17, Caddy and the free subdomain with HTTPS; deploy; run migrations; create the owner account.
- **Restore test** on a second throwaway VM or a local VM; record the minutes taken in `docs/deployment.md`.
- Production guard checks: demo verifier off, `APP_ENV=production`, no default secrets, and the app refuses to start otherwise.

**Handover**
- `docs/user-guide.md`: plain-language guides for owner and staff, with screenshots from the demo data. Topics: sign in, register a driver, KYC, autos, agreements, daily pay requests, recording payments, statement upload and approval, escalations, reports, backups.
- `docs/handover.md`: where everything runs, how to deploy, rotate keys, restore, and add staff; free-tier risks.
- A UAT checklist for the client, with sign-off lines.

## Tests to write first

- Every report total equals the ledger query total for the same filters (one test per report key).
- An Excel export opens and its totals row equals the API totals.
- Dashboard numbers equal the underlying queries on the seed data.
- Staff without `reports.all` cannot see business-wide totals (404 or 403 per policy).
- The production startup guard refuses unsafe configuration.
- Playwright flows 1–3 pass against a local build.

## Done when

- [ ] The ASVS level 1 review is recorded with no open high items.
- [ ] The app runs at the free subdomain over HTTPS, with backups running and a restore tested.
- [ ] The user guide and handover notes are written; the client's UAT checklist is ready.
- [ ] `check.ps1` and the Playwright flows are green.

## You check

1. On your phone at the live address: sign in as staff, onboard a fake driver end to end.
2. As the owner: approve, escalate, export a report to Excel, and verify the audit chain.
3. Read the user guide as if you were the client's newest staff member.
