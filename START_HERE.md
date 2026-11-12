# Start here: building the Auto Rental Management System with Claude Code

This kit holds everything Claude Code needs to build the app one week at a time. It does not contain the code yet; Claude Code writes that, starting with Week 1.

## 1. Install the free tools (once, on Windows)

| Tool | Why | Check it with |
| --- | --- | --- |
| Git for Windows | Version control | `git --version` |
| Python 3.12 (the project uses 3.12 even if a newer one is installed) | Backend | `py -3.12 --version` |
| Node.js LTS | Frontend and Claude Code | `node --version` and `npm --version` |
| PostgreSQL 17 (Windows installer) | Database | `psql --version` |
| Claude Code | The AI developer in your terminal; uses your own Claude plan | `claude --version` |

Install Claude Code using Anthropic's current instructions at docs.claude.com (for example `npm install -g @anthropic-ai/claude-code`).

When the PostgreSQL installer asks for a password for the `postgres` user, write it down; Week 1 needs it.

## 2. Put the kit in the project folder

Open **PowerShell** and run:

```powershell
# Create the projects folder and unzip the kit into it
New-Item -ItemType Directory -Force -Path "E:\Projects"
Expand-Archive -Path "$HOME\Downloads\AutoRentalManagementSystem-kit.zip" -DestinationPath "E:\Projects" -Force

# Go into the project and start version control
Set-Location "E:\Projects\AutoRentalManagementSystem"
git init
git add .
git commit -m "Add Claude Code kit: plan v2, rules, milestone briefs"
```

If the zip was saved somewhere other than Downloads, change the path in `Expand-Archive`.

## 3. Start Week 1

```powershell
Set-Location "E:\Projects\AutoRentalManagementSystem"
claude
```

Inside Claude Code, type:

```
/milestone 01
```

Claude Code reads `CLAUDE.md` and the Week 1 brief, checks your computer (Python, Node, PostgreSQL), and shows a plan. **It waits for your approval before writing code.** Read the plan, ask questions, then say "approved".

If `/milestone` is not recognised, paste this instead:

```
Read CLAUDE.md, docs/business-rules.md, docs/open-questions.md and docs/milestones/week-01.md. Check the repo and my environment, then present your plan for this milestone and wait for my approval before writing code.
```

## 4. The weekly rhythm

1. `/milestone NN` and approve the plan.
2. Claude Code writes the rule tests first, builds, and runs `.\scripts\check.ps1` until everything passes.
3. You try it yourself using the steps it gives you, and tick the brief's "You check" list.
4. Run `/review` for an independent check against the rules, then commit.
5. Move to the next week only when the "Done when" list is complete.

Other commands in this kit:

- `/check`: run all tests and checks and fix what fails, without weakening tests.
- `/review`: review the current changes against the hard constraints and business rules. It changes nothing.

## 5. When the client answers a question

Open `docs/open-questions.md`, write the answer in the **Answer** column, and tell Claude Code: "N3 is answered, see open-questions.md; update the code and tests." Most defaults are settings, so most answers are a small change.

## 6. What the client sets up (all free)

- A merchant UPI ID or QR from the business's bank (Week 6 needs it).
- An Oracle Cloud Always Free account. The client creates it early, outside the code (sign-up asks for a card to verify identity); no server work happens until Week 8, when we deploy and go live.
- A free email account for system emails.
- Test Aadhaar QR and licence lookups use **made-up data only** until go-live.
