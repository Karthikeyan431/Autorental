# Handover notes

Started in Week 3; Week 8 completes this document (where everything runs, deploying, restoring,
adding staff, free-tier risks).

## Secrets and keys to back up

The production `backend/.env` holds keys that are **not** inside the database backups. Keep a
copy of each in the owner's password manager or a sealed offline copy, separate from the data
backups (`docs/deployment.md`, "Backups"):

| Key | Why it matters | Rotation |
| --- | --- | --- |
| `SECRET_KEY` | Signs sign-in tokens | Rotating signs everyone out |
| `FIELD_ENCRYPTION_KEY`, `FIELD_ENCRYPTION_KEY_ID` | Decrypts licence numbers and the owner's TOTP secret | Add a new key id; old ids must stay available |
| `FILE_ENCRYPTION_KEYS`, `ACTIVE_FILE_KEY_ID` | Decrypts every stored document and photo | Add a new key id; old ids must stay available |
| `LOOKUP_HMAC_KEY` | Duplicate checks for licence numbers | **Never rotate.** Losing or changing it breaks duplicate detection for every stored licence number (D36) |

## Owner account recovery

Use this when the owner forgets their password, is locked out, or loses the phone with the
authenticator app (and has no recovery codes left). It needs shell access to the server: there
is no recovery through the web app, by design.

1. Sign in to the server (production: SSH as the deploy user; development: a PowerShell window
   in the repository folder).
2. Run the recovery command and answer the prompts:
   - Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\reset-password.ps1`
   - Ubuntu server (layout in `docs/deployment.md`; Week 8 confirms the exact command):
     `sudo -u arms bash -c 'set -a; . /etc/arms/arms.env; cd /srv/arms/app/backend && /srv/arms/venv/bin/python -m app.cli.reset_password'`
3. Type the owner's mobile number or email, then the new password twice (hidden; at least 10
   characters, not common, not the owner's name or mobile).
4. Add `-ResetTotp` (Windows) or `--reset-totp` (Ubuntu) **only** if the authenticator app is
   lost. The owner then sets up a new authenticator app at the next sign-in and gets new
   recovery codes; the old codes stop working.
5. Sign in at the web app with the new password. The app asks for a new password straight
   away (the one typed in the shell was seen by whoever ran the command).

What the command does, in one transaction: sets the password, clears the lockout and failed
attempts, signs the user out on every device, forces a password change at the next sign-in,
optionally clears the 2-step setup, and writes an audit entry `user.password_reset_cli` with
actor `system:cli` (no password, name or mobile is stored in the audit log). It works the same
for a staff member, although the owner can also reset staff passwords from the Staff screen;
`-ResetTotp` is refused for staff, who do not use an authenticator app.

The command works in every environment, including production, because anyone who can run it
can already read the database. Protect shell access to the server accordingly (SSH keys only,
`docs/deployment.md`).
