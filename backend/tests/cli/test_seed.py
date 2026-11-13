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
from app.core.security import verify_password
from app.modules.drivers.models import Driver
from app.modules.drivers.pii import decrypt_driver_field
from app.modules.kyc.models import KycCheck, LicenceDetails
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User
from app.modules.users.service import create_owner
from app.modules.vehicles.models import Vehicle
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


def test_cli_seeds_in_a_fresh_process(
    test_settings: Settings, app_engine: Engine, clean_db: None, tmp_path: Path
) -> None:
    # A fresh interpreter catches missing model imports that the test process would hide.
    result = _run_cli(
        {
            "APP_ENV": "development",
            "DATABASE_URL": test_settings.DATABASE_URL,
            "SEED_DEV_PASSWORD": "Seed-dev-pass-0001",
            "DOCUMENTS_DIR": str(tmp_path),
            "FILE_ENCRYPTION_KEYS": test_settings.FILE_ENCRYPTION_KEYS.get_secret_value(),
            "ACTIVE_FILE_KEY_ID": test_settings.ACTIVE_FILE_KEY_ID,
            "LOOKUP_HMAC_KEY": test_settings.LOOKUP_HMAC_KEY.get_secret_value(),
        }
    )
    assert result.returncode == 0, result.stderr
    assert "settings version" in result.stdout.lower()
    assert "Seed-dev-pass-0001" not in result.stdout + result.stderr
    with Session(app_engine) as check:
        assert check.scalar(select(func.count()).select_from(SettingsVersion))
        assert check.scalar(select(func.count()).select_from(User)) == 3
        assert check.scalar(select(func.count()).select_from(Driver)) == 5


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


SEED_PASSWORD = "Seed-dev-pass-0001"


def _dev(tmp_path: Path, **extra: object) -> Settings:
    return make_settings(APP_ENV="development", DOCUMENTS_DIR=tmp_path, **extra)


def test_seed_adds_a_fake_owner_and_two_staff(owner_db: Session, tmp_path: Path) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD))
    users = owner_db.scalars(select(User).order_by(User.id)).all()

    assert [u.role for u in users] == ["owner", "staff", "staff"]
    for user in users:
        assert user.mobile.startswith("+9190000")
        assert "Test" in user.name
        assert user.email is None or user.email.endswith(".test")
        assert verify_password(user.password_hash, SEED_PASSWORD)
        assert user.must_change_password is False

    assert seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD)) is False
    assert owner_db.scalar(select(func.count()).select_from(User)) == 3


def test_seed_skips_users_without_a_dev_password(owner_db: Session) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    seed(owner_db, make_settings(APP_ENV="development"))
    assert owner_db.scalar(select(func.count()).select_from(User)) == 0


def test_seed_refuses_a_weak_dev_password(owner_db: Session) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    with pytest.raises(SeedRefusedError):
        seed(owner_db, make_settings(APP_ENV="development", SEED_DEV_PASSWORD="1234567890"))


def test_seed_keeps_an_existing_owner(owner_db: Session, tmp_path: Path) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    create_owner(
        owner_db, name="Test Owner Real", mobile="9000000099", email=None, password=SEED_PASSWORD
    )
    seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD))
    owners = owner_db.scalars(select(User).where(User.role == "owner")).all()
    assert [o.name for o in owners] == ["Test Owner Real"]


def test_seed_refuses_a_dev_password_with_a_demo_users_name(owner_db: Session) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    with pytest.raises(SeedRefusedError):
        seed(owner_db, make_settings(APP_ENV="development", SEED_DEV_PASSWORD="Demo-river-2026"))


def test_seed_adds_five_obviously_fake_drivers(owner_db: Session, tmp_path: Path) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    settings = _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD)
    seed(owner_db, settings)
    drivers = owner_db.scalars(select(Driver).order_by(Driver.id)).all()

    assert [d.full_name for d in drivers] == [f"Test Driver {n:03d} (DEMO)" for n in range(1, 6)]
    for driver in drivers:
        assert driver.mobile.startswith("+9190000")
        # The address is encrypted at rest (N15, D46); decrypted it is still visibly fake.
        assert "DEMO" not in driver.address
        assert "DEMO" in decrypt_driver_field(settings, "address", driver.id, driver.address)
    statuses = {
        (c.driver_id, c.check_type): c.status
        for c in owner_db.scalars(select(KycCheck).where(KycCheck.is_current))
    }
    assert statuses[(drivers[0].id, "identity")] == "approved"
    assert statuses[(drivers[0].id, "licence")] == "approved"
    for details in owner_db.scalars(select(LicenceDetails)):
        assert details.licence_number_last4.isdigit()
        assert "DEMO" in (details.issuing_authority or "")
    for value in [d.address for d in drivers]:
        assert not re.search(r"\d{12}", value)

    # Safe to run again: nothing is duplicated.
    assert seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD)) is False
    assert owner_db.scalar(select(func.count()).select_from(Driver)) == 5


def test_seed_adds_five_obviously_fake_autos(owner_db: Session, tmp_path: Path) -> None:
    """Week 4: "XX" is not a state code, so these can never be real registrations."""
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD))
    autos = owner_db.scalars(select(Vehicle).order_by(Vehicle.registration_number)).all()
    assert [v.registration_number for v in autos] == [f"XX00TT{n:04d}" for n in range(1, 6)]
    assert all("DEMO" in v.make for v in autos)
    assert {v.status for v in autos} <= {"available", "maintenance"}

    seed(owner_db, _dev(tmp_path, SEED_DEV_PASSWORD=SEED_PASSWORD))
    assert owner_db.scalar(select(func.count()).select_from(Vehicle)) == 5


def test_seed_skips_drivers_without_staff(owner_db: Session, tmp_path: Path) -> None:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    seed(owner_db, _dev(tmp_path))
    assert owner_db.scalar(select(func.count()).select_from(Driver)) == 0
