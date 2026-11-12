# Deployment templates (placeholders until Week 8)

Nothing here is used yet: **no server work happens before Week 8** (decision D3). These files
are templates taken from `docs/deployment.md` so the layout is settled early.

| File | Purpose |
| --- | --- |
| `Caddyfile` | HTTPS (Let's Encrypt), static frontend, `/api/*` proxy, security headers |
| `systemd/arms-api.service` | uvicorn, 2 workers, bound to 127.0.0.1:8000 |
| `systemd/arms-jobs.service` + `.timer` | idempotent jobs (accrual, pay requests, alerts) every 15 minutes |
| `systemd/arms-backup.service` + `.timer` | nightly encrypted backup (script written in Week 8) |

Week 8 adds `deploy.sh`, the backup script, `MOVE.md` and the restore test.

Target: Oracle Cloud Always Free, Ubuntu 24.04 arm64, PostgreSQL 17 on localhost,
app in `/srv/arms/app`, venv in `/srv/arms/venv`, environment in `/etc/arms/arms.env`
(root:arms, 0640). Every value in `arms.env` follows `backend/.env.example`; the app refuses
to start in production with the demo verifier on or with weak secrets.
