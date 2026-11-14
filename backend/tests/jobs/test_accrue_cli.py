"""`python -m app.jobs.accrue` in a fresh process (D20): without a rent due time it writes nothing
and exits non-zero with "Set the rent due time in Settings"; after the owner sets it, one run
fills every day from the start date to today, and a second run adds nothing."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import business_date
from app.modules.rent.models import RentCharge
from tests.rent_helpers import (
    make_agreement,
    make_driver,
    make_settings_version,
    make_user,
    make_vehicle,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _run(test_settings: Settings) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "APP_ENV": "development", "DATABASE_URL": test_settings.DATABASE_URL}
    return subprocess.run(  # fixed arguments, no shell
        [sys.executable, "-m", "app.jobs.accrue"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _count(engine: Engine) -> int:
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(RentCharge)) or 0)


def test_accrual_cli_refuses_without_a_due_time_then_fills_the_days(
    test_settings: Settings, app_engine: Engine, clean_db: None
) -> None:
    today = business_date()
    with Session(app_engine) as setup, setup.begin():
        staff = make_user(setup)
        make_agreement(
            setup,
            make_driver(setup, staff),
            make_vehicle(setup, status="rented"),
            staff,
            start=today - timedelta(days=3),
            status="active",
        )

    refused = _run(test_settings)
    assert refused.returncode == 1
    assert "Set the rent due time in Settings" in refused.stderr
    assert _count(app_engine) == 0

    with Session(app_engine) as setup, setup.begin():
        make_settings_version(setup)
    first = _run(test_settings)
    assert first.returncode == 0, first.stderr
    assert "4 charges" in first.stdout
    assert _count(app_engine) == 4  # three days ago to today

    again = _run(test_settings)
    assert again.returncode == 0, again.stderr
    assert "0 charges" in again.stdout
    assert _count(app_engine) == 4
