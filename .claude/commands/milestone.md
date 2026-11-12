---
description: Plan and build one milestone from docs/milestones (e.g. /milestone 03)
argument-hint: <week number, e.g. 01>
---

We are working on milestone week $ARGUMENTS.

1. Read `CLAUDE.md`, `docs/business-rules.md`, `docs/open-questions.md` and `docs/milestones/week-$ARGUMENTS.md`, plus every doc that brief lists under "Read first".
2. Inspect the repository for this milestone: what already exists, what is missing, and whether `.\scripts\check.ps1` currently passes (if it exists yet).
3. Present a plan:
   - the files you will add or change;
   - migrations;
   - endpoints;
   - screens;
   - the tests you will write first, mapped to the brief's "Tests to write first" list;
   - any question or decision you need from me;
   - anything in the brief that conflicts with `CLAUDE.md` or `docs/business-rules.md`.
   Then **stop and wait for my approval**.
4. After I approve:
   - Write the business-rule tests first and run them to show they fail for the right reason.
   - Implement in small steps.
   - Run `.\scripts\check.ps1` until it is green. Never weaken, skip or delete a test to get there.
5. Finish with:
   - what was built;
   - exact steps for me to try it;
   - the test results;
   - the brief's "Done when" checklist, ticked or not with reasons;
   - anything deferred;
   - suggested commit message(s).

Do not start the next milestone. Do not add paid services or unlisted dependencies without asking.
