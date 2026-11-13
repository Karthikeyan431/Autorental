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
