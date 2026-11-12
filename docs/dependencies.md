# Dependencies

Every dependency must be **free and open source** (hard constraint 1). Versions are pinned exactly; the lock files (`backend/requirements.lock`, `frontend/package-lock.json`) are the final word. Update this file whenever a package is added or upgraded, and ask before adding anything not listed in `CLAUDE.md`.

Versions below are the current stable releases on 12 November 2026. "Week" is when the package is first installed; a later-week package is re-checked for a newer stable version when it is added.

## Backend (Python 3.12)

| Package | Version | Licence | Week | Purpose |
| --- | --- | --- | --- | --- |
| fastapi | 0.162.5 | MIT | 1 | Web framework |
| pydantic | 2.14.3 | MIT | 1 | Validation |
| pydantic-settings | 2.16.2 | MIT | 1 | Config from the environment |
| sqlalchemy | 2.1.8 | MIT | 1 | ORM and SQL |
| alembic | 1.20.1 | MIT | 1 | Migrations |
| psycopg[binary] | 3.3.9 | LGPL-3.0-only | 1 | PostgreSQL driver (used unmodified as a library) |
| uvicorn | 0.54.0 | BSD-3-Clause | 1 | ASGI server |
| httpx | 0.28.1 | BSD-3-Clause | 1 | Test client (dev) |
| pytest | 9.2.0 | MIT | 1 | Tests (dev) |
| ruff | 0.17.4 | MIT | 1 | Lint and format (dev) |
| mypy | 2.4.1 | MIT | 1 | Type checks (dev) |
| pip-audit | 2.10.1 | Apache-2.0 | 1 | Vulnerability audit (dev) |
| argon2-cffi | 25.1.0 | MIT | 2 | Password hashing |
| pyjwt | 2.15.1 | MIT | 2 | Access tokens |
| pyotp | 2.10.0 | MIT | 2 | Owner TOTP |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | 2 | AES-256-GCM |
| python-multipart | 0.0.33 | Apache-2.0 | 3 | File uploads |
| pillow | 13.0.0 | MIT-CMU | 3 | EXIF strip, resize |
| reportlab | 5.1.0 | BSD | 5 | Agreement and receipt PDFs |
| apscheduler | 3.11.3 | MIT | 5 | Development scheduling only (production uses the systemd timer) |
| qrcode | 8.2 | BSD (re-check: PyPI metadata also shows an "Other/Proprietary" classifier) | 6 | Pay request QR PNG |
| openpyxl | 3.1.5 | MIT | 7 | Bank statement XLSX, Excel export |
| pywebpush | 2.5.0 | MPL-2.0 | 7 | Web Push |

## Frontend (Node 24)

| Package | Version | Licence | Week | Purpose |
| --- | --- | --- | --- | --- |
| react, react-dom | 19.3.1 | MIT | 1 | UI |
| typescript | 6.0.3 | Apache-2.0 | 1 | Types. 7.0.2 is newer, but `typescript-eslint` 8.72 supports only `<6.1` |
| vite | 8.3.8 | MIT | 1 | Dev server and build |
| tailwindcss, @tailwindcss/vite | 4.3.5 | MIT | 1 | Styles |
| react-router | 8.5.1 | MIT | 1 | Routing |
| @tanstack/react-query | 5.107.1 | MIT | 1 | Server state |
| react-hook-form | 7.92.0 | MIT | 1 | Forms |
| zod | 4.6.7 | MIT | 1 | Schemas |
| vitest | 5.1.0 | MIT | 1 | Tests (dev) |
| @testing-library/react | 16.3.3 | MIT | 1 | Component tests (dev) |
| eslint | 10.14.0 | MIT | 1 | Lint (dev) |
| prettier | 3.10.1 | MIT | 1 | Format (dev) |
| @zxing/browser | 0.2.1 | MIT | 4 | Aadhaar QR scanning (behind a flag) |
| @playwright/test | 1.65.0 | Apache-2.0 | 8 | End-to-end tests (dev) |

Supporting packages that the approved tools need (for example `@vitejs/plugin-react`, `typescript-eslint`, `@types/react`) are added here once approved in the Week 1 plan.

## Free tools outside the lock files

PostgreSQL 17, Caddy, `age`, `rclone` (Week 8, on the server). `pip-audit` and `npm audit` read public vulnerability databases at no cost.
