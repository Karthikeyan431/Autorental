---
description: Run all checks and fix failures without weakening tests
---

Run `.\scripts\check.ps1`. For each failure, find and fix the cause in the code. Never weaken, skip or delete a test, and never loosen a lint or type rule to make it pass. If a failure shows that a test itself is wrong, explain why and ask before changing it. Re-run until green, then summarise what was fixed.
