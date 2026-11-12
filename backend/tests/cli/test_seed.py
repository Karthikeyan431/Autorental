"""The seed loads only obviously fake data and never runs in production."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.cli.seed import SeedRefusedError, seed
from app.core.config import Settings
from app.modules.settings.models import SettingsVersion
from tests.helpers import make_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run_cli(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `python -m app.cli.seed` in a fresh interpreter, as a developer would."""
    env = {**os.environ, **env_overrides}
    return subprocess.run(  # fixed arguments, no shell
        [sys.executable, "-m", "app.cli.seed"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cli_seeds_in_a_fresh_process(test_settings: Settings, app_engine: Engine) -> None:
    # A fresh interpreter catches missing model imports that the test process would hide.
    result = _run_cli({"APP_ENV": "development", "DATABASE_URL": test_settings.DATABASE_URL})
    assert result.returncode == 0, result.stderr
    assert "settings version" in result.stdout.lower() or "already present" in result.stdout
    with Session(app_engine) as check:
        assert check.scalar(select(func.count()).select_from(SettingsVersion))


def test_cli_refuses_production(test_settings: Settings) -> None:
    result = _run_cli({"APP_ENV": "production", "DATABASE_URL": test_settings.DATABASE_URL})
    assert result.returncode == 2
    assert "production" in result.stderr


def test_seed_refuses_production(owner_db: Session) -> None:
    with pytest.raises(SeedRefusedError):
        seed(owner_db, make_settings(APP_ENV="production"))
    assert owner_db.scalar(select(func.count()).select_from(SettingsVersion)) is not None


def test_seed_inserts_the_first_settings_version_once(owner_db: Session) -> None:
    owner_db.execute(text("DELETE FROM settings_versions"))
    settings = make_settings(APP_ENV="development")

    assert seed(owner_db, settings) is True
    assert seed(owner_db, settings) is False  # safe to run twice
    assert owner_db.scalar(select(func.count()).select_from(SettingsVersion)) == 1


def test_seeded_business_details_are_visibly_fake(owner_db: Session) -> None:
    owner_db.execute(text("DELETE FROM settings_versions"))
    seed(owner_db, make_settings(APP_ENV="development"))
    version = owner_db.scalars(select(SettingsVersion)).one()

    assert version.business_name is not None
    assert "DEMO" in version.business_name
    assert version.upi_payee_name is not None
    assert "DEMO" in version.upi_payee_name
    assert version.business_upi_id is not None
    assert version.business_upi_id.startswith("demo")
    for value in (version.business_name, version.business_address or "", version.upi_payee_name):
        assert not re.search(r"\d{10}", value), "no real-looking phone or ID numbers"
