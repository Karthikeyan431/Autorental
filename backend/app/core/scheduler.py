"""Development scheduling (APScheduler): rent accrual every 15 minutes inside the API process.

On only when `APP_ENV=development` and `DEV_SCHEDULER_ENABLED=true`; production refuses to start
with the flag on and uses the systemd timer instead (Week 8). The job is the same idempotent
accrual as `python -m app.jobs.accrue`, in its own transaction. Logs carry counts only.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.rent.accrual import accrue

_log = logging.getLogger("arms.scheduler")
ACCRUAL_MINUTES = 15


def run_accrual(factory: sessionmaker[Session]) -> None:
    try:
        with factory() as session, session.begin():
            result = accrue(session)
    except AppError as exc:
        _log.warning("rent accrual skipped: %s", exc.code)
        return
    _log.info(
        "rent accrual: %d charges for %d agreements", result.charges_created, result.agreements
    )


def start_dev_scheduler(
    settings: Settings, factory: sessionmaker[Session]
) -> BackgroundScheduler | None:
    if settings.APP_ENV != "development" or not settings.DEV_SCHEDULER_ENABLED:
        return None
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(
        run_accrual,
        "interval",
        minutes=ACCRUAL_MINUTES,
        args=[factory],
        id="rent-accrual",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    run_accrual(factory)  # once at start, like production's "also on app start"
    return scheduler
