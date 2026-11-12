"""Load obviously fake demo data into the development database.

    python -m app.cli.seed

Week 1 seeds only the first settings version. Later weeks add users (Week 2, password from
SEED_DEV_PASSWORD), drivers (Week 3) and autos (Week 4). Never runs when APP_ENV=production.
Safe to run more than once.
"""

import sys
from datetime import time

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import SettingsChanges
from app.modules.settings.service import create_settings_version

DEMO_SETTINGS = SettingsChanges(
    rent_due_time=time(10, 0),  # demo value from the worked example in rent-and-payments.md
    business_name="Test Auto Rentals (DEMO)",
    business_address="DEMO address, not a real place",
    business_upi_id="demo@upi",
    upi_payee_name="DEMO Payee",
)


class SeedRefusedError(RuntimeError):
    """The seed must never run against production."""


def seed(session: Session, settings: Settings) -> bool:
    """Seed into the caller's transaction. Returns True if anything was inserted."""
    if settings.is_production:
        raise SeedRefusedError("The seed refuses to run when APP_ENV=production.")

    if session.scalar(select(exists().where(SettingsVersion.id.is_not(None)))):
        return False
    create_settings_version(
        session, DEMO_SETTINGS, actor_id=None, reason="Development seed (fake data)"
    )
    return True


def main() -> int:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed: APP_ENV=production.", file=sys.stderr)
        return 2
    engine = make_engine(settings.DATABASE_URL)
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            created = seed(session, settings)
    finally:
        engine.dispose()
    print("Seeded the first settings version." if created else "Seed data already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
