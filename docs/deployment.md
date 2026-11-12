# Deployment on free hosting

Everything here is free. The one risk is that Oracle's free tier has no guarantee: it was halved in 2026 without notice. Keep off-site backups and a tested restore, so the app can move to another host in a day.

## Target

- **Oracle Cloud Always Free:** one Ampere A1 (Arm64) VM, 2 OCPU and 12 GB memory, in the client's home region; one boot volume (about 100 GB of the 200 GB free block storage). Ubuntu 24.04 LTS (arm64).
- **Object Storage** (Always Free) for encrypted backups.
- **Free subdomain** pointing at the VM's public IP (for example DuckDNS). **Caddy** gets and renews Let's Encrypt certificates automatically.

## Server layout

```
/srv/arms/app/            git checkout (deploy user, read-only for the app)
/srv/arms/venv/           Python virtualenv
/srv/arms/frontend-dist/  built frontend, served by Caddy
/srv/arms/data/files/     encrypted documents (app user only, 0700)
/etc/arms/arms.env        environment file (root:arms, 0640)
```

- **systemd units:** `arms-api.service` (uvicorn, 2 workers, bound to 127.0.0.1:8000), `arms-jobs.timer` and `arms-jobs.service` (accrual, pay requests, alerts every 15 minutes), `arms-backup.timer` (nightly).
- **PostgreSQL 17:** local only (listen on localhost). Two roles: `app_owner` (migrations) and `app_user` (runtime).
- **Caddy:** serves `frontend-dist`, proxies `/api/*` to 127.0.0.1:8000, adds the security headers, and enables HTTP/2 and HTTP/3.

## Network

- Oracle security list: allow 22 (SSH, from the admin IP if possible), 80 and 443 only. Mirror this with `ufw`.
- SSH with keys only; root login and password login disabled. `unattended-upgrades` on for security updates.

## Deploy steps (Week 8; write them as `deploy/deploy.sh`)

1. `git pull` on the tag being released.
2. `pip install -r backend/requirements.lock` into the venv.
3. `alembic upgrade head` as `app_owner`.
4. `npm ci && npm run build` in `frontend/`, then copy `dist/` to `frontend-dist/`.
5. `systemctl restart arms-api`, then check `/api/v1/health`.

## Backups (nightly, free)

- `pg_dump -Fc` and a tar of `data/files/`, encrypted with `age` to the owner's public key, uploaded to Object Storage with `rclone` (free). Keep 14 nightly backups.
- **Weekly:** the owner downloads the latest backup from Settings and keeps it offline.

## Restore test (Week 8; record the time taken)

1. Create a fresh VM.
2. Install from this document.
3. Download the latest backup and decrypt it with the owner's key.
4. Run `pg_restore`, and extract the files.
5. Run `/api/v1/audit-logs/verify`, then log in and spot-check 3 drivers' ledgers.

## Move plan (if Oracle's free tier changes)

The same steps work on any Ubuntu server, paid or free. DNS moves by updating the subdomain's IP. Write the exact commands in `deploy/MOVE.md` in Week 8.
