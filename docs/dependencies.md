# Dependencies

Every dependency must be **free and open source** (hard constraint 1). Versions are pinned exactly; the lock files (`backend/requirements.lock`, `backend/requirements-dev.lock`, `frontend/package-lock.json`) are the final word. Update this file whenever a package is added or upgraded, and ask before adding anything not listed in `CLAUDE.md`.

**Registry check:** every Week 1 version below was confirmed against PyPI (`pip index versions`) and npm (`npm view`) on **2026-11-12**, immediately before installing. The Week 2 packages (argon2-cffi, pyjwt, pyotp, cryptography, qrcode, react-hook-form, zod, @hookform/resolvers) were re-checked on **2026-11-13** and are installed. The Week 3 packages (python-multipart, pillow) were re-checked on **2026-11-13** and are installed; neither adds a dependency of its own. The Week 5 packages (reportlab 5.1.0, apscheduler 3.11.3) were re-checked on **2026-11-14** (still the latest) and are installed. Packages for later weeks show the latest version on that date and are re-checked when they are added.

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
| tzdata | 2026.6 | Apache-2.0 | 1 | IANA time zones on Windows (`Asia/Kolkata`; never a hardcoded offset) |
| httpx | 0.28.1 | BSD-3-Clause | 1 | Test client (dev) |
| pytest | 9.2.0 | MIT | 1 | Tests (dev) |
| ruff | 0.17.5 | MIT | 1 | Lint and format (dev) |
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
| qrcode | 8.2 | BSD-3-Clause (checked 2026-11-13: the shipped LICENSE is BSD-3-Clause plus the MIT notice of the code it was ported from; the extra "Other/Proprietary" PyPI classifier has no licence text behind it) | 2 | Owner TOTP setup QR (SVG, no Pillow needed); pay request QR in Week 6 |
| openpyxl | 3.1.5 | MIT | 7 | Bank statement XLSX, Excel export |
| pywebpush | 2.5.0 | MPL-2.0 | 7 | Web Push |

Transitive runtime packages (Starlette, anyio, Mako, python-dotenv and others) are pinned in `requirements.lock`. Week 2 added argon2-cffi-bindings 26.1.0 (MIT), cffi 2.1.1 (MIT-0), pycparser 3.12 (BSD-3-Clause) and colorama 0.4.6 (BSD-3-Clause, a qrcode dependency on Windows). Week 5 added charset-normalizer 3.5.2 (MIT, a reportlab dependency) and tzlocal 5.4.5 (MIT, an APScheduler dependency); the existing pins were kept (no unrelated upgrade).

`reportlab` and APScheduler 3 ship no type hints either; mypy ignores missing imports for them only (`pyproject.toml`), rather than adding stub packages.

`qrcode` ships no type hints. Rather than add `types-qrcode`, mypy ignores missing imports for `qrcode` only (`pyproject.toml`).

**Known notice (D19):** Starlette prints a deprecation warning that its test client should move from `httpx` to `httpx2`. Tests pass. Decision: keep `httpx` for now and revisit when Starlette drops `httpx` support.

## Frontend (Node 24 or newer)

| Package | Version | Licence | Week | Purpose |
| --- | --- | --- | --- | --- |
| react, react-dom | 19.3.1 | MIT | 1 | UI |
| react-router | 8.5.1 | MIT | 1 | Routing |
| @tanstack/react-query | 5.107.1 | MIT | 1 | Server state |
| typescript | 6.0.3 | Apache-2.0 | 1 | Types. 7.0.2 is newer, but `typescript-eslint` 8.72 supports only `<6.1` |
| vite | 8.3.8 | MIT | 1 | Dev server and build |
| @vitejs/plugin-react | 6.3.0 | MIT | 1 | React support for Vite |
| @vitejs/plugin-basic-ssl | 2.3.0 | MIT | 3 | Self-signed HTTPS for `dev.ps1 -Lan` only (dev) |
| tailwindcss, @tailwindcss/vite | 4.3.5 | MIT | 1 | Styles |
| vitest | 5.1.0 | MIT | 1 | Tests (dev) |
| jsdom | 31.0.0 | MIT | 1 | Browser environment for tests (dev) |
| @testing-library/react | 16.3.3 | MIT | 1 | Component tests (dev) |
| @testing-library/dom | 10.4.2 | MIT | 1 | Peer of the above (dev) |
| @testing-library/jest-dom | 7.0.1 | MIT | 1 | DOM matchers (dev) |
| @testing-library/user-event | 14.6.10 | MIT | 1 | User interaction in tests (dev) |
| eslint | 10.14.0 | MIT | 1 | Lint (dev) |
| @eslint/js | 10.0.1 | MIT | 1 | ESLint recommended rules (dev) |
| typescript-eslint | 8.72.2 | MIT | 1 | TypeScript lint rules (dev) |
| eslint-plugin-react-hooks | 7.1.1 | MIT | 1 | Hooks rules (dev) |
| eslint-plugin-react-refresh | 0.5.7 | MIT | 1 | Fast-refresh rules (dev) |
| globals | 17.14.0 | MIT | 1 | Browser globals for ESLint (dev) |
| prettier | 3.10.1 | MIT | 1 | Format (dev) |
| @types/react, @types/react-dom | 19.3.0 | MIT | 1 | Types (dev) |
| @types/node | 24.19.2 | MIT | 1 | Types for config files (dev) |
| react-hook-form | 7.92.0 | MIT | 2 | Forms |
| zod | 4.6.7 | MIT | 2 | Schemas |
| @hookform/resolvers | 7.0.6 | MIT | 2 | zod with react-hook-form (approved 2026-11-13) |
| @zxing/browser | 0.2.1 | MIT | 4 | Aadhaar QR scanning (behind a flag) |
| @playwright/test | 1.65.0 | Apache-2.0 | 8 | End-to-end tests (dev) |

Week 2 added the transitive package `@standard-schema/utils` 0.3.0 (MIT), pinned in `package-lock.json`.

### npm override (approved, D18)

`package.json` overrides **minimatch to 11.0.8** (MIT). ESLint 10.14 and typescript-eslint 8.72.2 require `minimatch` ^10, and every 10.x release is affected by GHSA-g3hv-75wg-m249 (moderate ReDoS, fixed in 11.0.1). The override applies to dev tooling only; production dependencies had no findings. ESLint was checked to still run and to still report errors with the override in place. Remove the override once ESLint and typescript-eslint depend on a fixed `minimatch`.

## Bundled data

| File | Source | Licence | Week | Purpose |
| --- | --- | --- | --- | --- |
| `backend/app/core/data/common-passwords.txt` | SecLists `Passwords/Common-Credentials/10k-most-common.txt`, https://github.com/danielmiessler/SecLists (downloaded 2026-11-13, unmodified) | MIT, Copyright (c) 2018 Daniel Miessler | 2 | Blocks the 10,000 most common passwords (compared ignoring case). Only about 50 entries are 10+ characters, so most of the protection comes from the 10-character minimum. |

## Free tools outside the lock files

PostgreSQL 17, Caddy, `age` and `rclone` (Week 8, on the server). `pip-audit` and `npm audit` read public vulnerability databases at no cost.
