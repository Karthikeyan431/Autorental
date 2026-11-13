"""scripts/db-setup.ps1 must never change the password of a role that already exists.

These tests run the real script with -DryRun and -EnvFile pointing at a temporary path, so
they cannot touch this machine's roles or backend/.env. The roles exist on any machine that
can run this suite (the other tests use them). After each run the test database must still
accept the current passwords.

The script is PowerShell and connects as the PostgreSQL superuser, so these tests need Windows
and a superuser password available without a prompt (PGPASSWORD or pgpass.conf).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

REPO_DIR = Path(__file__).resolve().parents[3]
SCRIPT = REPO_DIR / "scripts" / "db-setup.ps1"
EXIT_REFUSED = 2


def _superuser_password_available() -> bool:
    pgpass = Path(os.environ.get("APPDATA", "")) / "postgresql" / "pgpass.conf"
    return bool(os.environ.get("PGPASSWORD")) or pgpass.exists()


pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="db-setup.ps1 is a Windows script"),
    pytest.mark.skipif(
        not _superuser_password_available(),
        reason="needs PGPASSWORD or pgpass.conf to reach PostgreSQL as postgres without a prompt",
    ),
]


def _powershell() -> str:
    path = shutil.which("powershell.exe")
    assert path is not None, "Windows PowerShell was not found"
    return path


def _run(env_file: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    # Arguments are fixed: the repo's own script and a pytest tmp_path. No shell.
    return subprocess.run(  # noqa: S603
        [
            _powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-EnvFile",
            str(env_file),
            "-DryRun",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def _assert_current_passwords_still_work(app_engine: Engine) -> None:
    app_engine.dispose()  # force a fresh login with the password from backend/.env
    with app_engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1


def test_existing_roles_without_env_file_are_refused(tmp_path: Path, app_engine: Engine) -> None:
    # A fresh clone on a machine that is already set up.
    env_file = tmp_path / "missing.env"
    result = _run(env_file)
    assert result.returncode == EXIT_REFUSED, result.stdout + result.stderr
    assert "REFUSED" in result.stdout
    assert "-RotatePasswords" in result.stdout
    assert not env_file.exists()
    _assert_current_passwords_still_work(app_engine)


def test_existing_roles_with_env_file_keep_everything(tmp_path: Path, app_engine: Engine) -> None:
    env_file = tmp_path / "existing.env"
    original = "APP_ENV=development\nDATABASE_URL=postgresql+psycopg://app_user:abc@localhost/x\n"
    env_file.write_text(original, encoding="utf-8")

    result = _run(env_file)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "keep role app_owner and its existing password" in result.stdout
    assert "keep role app_user and its existing password" in result.stdout
    assert "rotate" not in result.stdout.lower()
    assert "Dry run: nothing was changed." in result.stdout
    assert env_file.read_text(encoding="utf-8") == original
    _assert_current_passwords_still_work(app_engine)


def test_rotate_is_explicit_and_dry_run_changes_nothing(tmp_path: Path, app_engine: Engine) -> None:
    env_file = tmp_path / "rotate.env"
    result = _run(env_file, "-RotatePasswords")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rotate the passwords of app_owner and app_user" in result.stdout
    assert "Dry run: nothing was changed." in result.stdout
    assert not env_file.exists()
    _assert_current_passwords_still_work(app_engine)


def test_passwords_are_never_printed(tmp_path: Path) -> None:
    result = _run(tmp_path / "rotate.env", "-RotatePasswords")
    combined = result.stdout + result.stderr
    assert "postgresql+psycopg://" not in combined
    assert "PASSWORD" not in combined.upper().replace("PASSWORDS", "")


def test_a_missing_lookup_key_is_added_to_an_existing_env_file(
    tmp_path: Path, app_engine: Engine
) -> None:
    # Week 3 added LOOKUP_HMAC_KEY: an older backend/.env gets it without other changes.
    env_file = tmp_path / "older.env"
    original = "APP_ENV=development\nDATABASE_URL=postgresql+psycopg://app_user:abc@localhost/x\n"
    env_file.write_text(original, encoding="utf-8")

    result = _run(env_file)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "add a new LOOKUP_HMAC_KEY" in result.stdout
    assert "Dry run: nothing was changed." in result.stdout
    assert env_file.read_text(encoding="utf-8") == original
    _assert_current_passwords_still_work(app_engine)


def test_an_existing_lookup_key_is_never_replaced(tmp_path: Path) -> None:
    env_file = tmp_path / "current.env"
    env_file.write_text(
        "APP_ENV=development\nLOOKUP_HMAC_KEY=existing-test-value\n", encoding="utf-8"
    )
    result = _run(env_file)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LOOKUP_HMAC_KEY" not in result.stdout
