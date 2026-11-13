"""Load obviously fake demo data into the development database.

    python -m app.cli.seed

Seeds the first settings version and, when SEED_DEV_PASSWORD is set, a fake owner and 2 fake
staff (Week 2) who all use that password. Later weeks add drivers (Week 3) and autos
(Week 4). Never runs when APP_ENV=production. Safe to run more than once.

The seeded owner has no authenticator yet: TOTP is set up at the first browser sign-in.
"""

import sys
from datetime import time

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.core.security import check_password_policy
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import SettingsChanges
from app.modules.settings.service import create_settings_version
from app.modules.users.models import User
from app.modules.users.service import create_owner, create_staff, owner_exists

DEMO_SETTINGS = SettingsChanges(
    rent_due_time=time(10, 0),  # demo value from the worked example in rent-and-payments.md
    business_name="Test Auto Rentals (DEMO)",
    business_address="DEMO address, not a real place",
    business_upi_id="demo@upi",
    upi_payee_name="DEMO Payee",
)


DEMO_OWNER = {"name": "Test Owner (DEMO)", "mobile": "9000000001", "email": "owner@demo.test"}
DEMO_STAFF = (
    {"name": "Test Staff 001 (DEMO)", "mobile": "9000000002", "email": "staff001@demo.test"},
    {"name": "Test Staff 002 (DEMO)", "mobile": "9000000003", "email": None},
)


class SeedRefusedError(RuntimeError):
    """The seed must never run against production, or with a weak dev password."""


def _seed_settings(session: Session) -> bool:
    if session.scalar(select(exists().where(SettingsVersion.id.is_not(None)))):
        return False
    create_settings_version(
        session, DEMO_SETTINGS, actor_id=None, reason="Development seed (fake data)"
    )
    return True


def _mobile_taken(session: Session, mobile: str) -> bool:
    return session.scalar(select(exists().where(User.mobile == f"+91{mobile}"))) is True


def _seed_users(session: Session, password: str) -> bool:
    try:
        check_password_policy(password)
    except AppError as exc:
        raise SeedRefusedError(f"SEED_DEV_PASSWORD is not acceptable: {exc.message}") from exc

    created = False
    if not owner_exists(session) and not _mobile_taken(session, DEMO_OWNER["mobile"] or ""):
        create_owner(
            session,
            name=DEMO_OWNER["name"] or "",
            mobile=DEMO_OWNER["mobile"] or "",
            email=DEMO_OWNER["email"],
            password=password,
        )
        created = True
    for staff in DEMO_STAFF:
        if _mobile_taken(session, staff["mobile"] or ""):
            continue
        create_staff(
            session,
            actor_id=None,
            name=staff["name"] or "",
            mobile=staff["mobile"] or "",
            email=staff["email"],
            password=password,
            must_change_password=False,
        )
        created = True
    return created


def seed(session: Session, settings: Settings) -> bool:
    """Seed into the caller's transaction. Returns True if anything was inserted."""
    if settings.is_production:
        raise SeedRefusedError("The seed refuses to run when APP_ENV=production.")

    created = _seed_settings(session)
    password = settings.SEED_DEV_PASSWORD.get_secret_value()
    if password:
        try:
            created = _seed_users(session, password) or created
        except AppError as exc:  # e.g. the password contains a demo user's name
            raise SeedRefusedError(f"SEED_DEV_PASSWORD is not acceptable: {exc.message}") from exc
    return created


def main() -> int:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed: APP_ENV=production.", file=sys.stderr)
        return 2
    engine = make_engine(settings.DATABASE_URL)
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            created = seed(session, settings)
    except SeedRefusedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(
        "Seeded the first settings version and demo users."
        if created
        else "Seed data already present."
    )
    if not settings.SEED_DEV_PASSWORD.get_secret_value():
        print("Demo users skipped: set SEED_DEV_PASSWORD in backend/.env to add them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
