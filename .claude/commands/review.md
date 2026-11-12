---
description: Review current changes against the hard constraints and business rules (read-only)
---

Review the uncommitted changes (`git diff` and `git status`, including new files) as a strict reviewer. **Do not change any files.** Report, with file and line:

1. Any breach of the hard constraints in `CLAUDE.md`:
   - a paid service or new dependency;
   - full Aadhaar handling;
   - personal data in logs;
   - a mock verifier usable in production;
   - real personal data in fixtures;
   - secrets in code;
   - floats used for money.
2. Any business rule in `docs/business-rules.md` that the change touches but does not enforce or test.
3. Write endpoints missing a permission check, a transaction or an audit entry.
4. Security issues: auth, file access, injection, missing rate limits, error messages that leak data.
5. Migrations: editing an applied migration, a missing downgrade, or a constraint that does not match `docs/data-model.md`.
6. Missing or weak tests for the milestone's "Tests to write first".

End with a verdict: **ready to commit** or **fix first**, and a short list of fixes in priority order.
