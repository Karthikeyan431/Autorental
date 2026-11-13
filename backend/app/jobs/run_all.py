"""Run every scheduled job once (production: the arms-jobs systemd timer).

    python -m app.jobs.run_all

Each job is idempotent and runs in its own transaction, so a failure in one does not undo
another. Output names counts only, never personal data.
"""

import sys

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.time import business_date
from app.jobs.licence_expiry import run_licence_expiry
from app.jobs.vehicle_papers import run_vehicle_papers
from app.modules.settings.schemas import SettingsValues
from app.modules.settings.service import get_current_settings


def main() -> int:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    today = business_date()
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            current = get_current_settings(session)
            alert_days = (
                current.licence_alert_days
                if current is not None
                else SettingsValues.model_fields["licence_alert_days"].default
            )
            result = run_licence_expiry(session, today, alert_days=alert_days)
        print(
            f"licence-expiry {today.isoformat()}: {result.expired} expired, "
            f"{result.alerts_created} alerts"
        )
        with make_sessionmaker(engine)() as session, session.begin():
            current = get_current_settings(session)
            vehicle_days = (
                current.vehicle_alert_days
                if current is not None
                else SettingsValues.model_fields["vehicle_alert_days"].default
            )
            papers = run_vehicle_papers(session, today, alert_days=vehicle_days)
        print(f"vehicle-papers {today.isoformat()}: {papers.alerts_created} alerts")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
