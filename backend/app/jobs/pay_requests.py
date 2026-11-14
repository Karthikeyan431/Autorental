"""Today's pay requests, once (docs/rent-and-payments.md §2; rule 18; N4):

    python -m app.jobs.pay_requests

Idempotent: a period that already has a request is left alone, so running it every 15 minutes
(production: the systemd timer, Week 8; development: APScheduler or by hand) is safe. It does
nothing before `pay_request_time` (default 08:00, Asia/Kolkata). Rent is accrued first, so
today's charge is included.

While the business UPI ID is not set it writes nothing, prints "Set the business UPI ID in
Settings" to stderr and exits 1. Output names counts only, never personal data.
"""

import sys
from datetime import datetime

from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core import time as clock
from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.modules.pay_requests.service import (
    UPI_ID_NOT_SET,
    GenerationResult,
    generate_pay_requests,
    require_upi_settings,
)
from app.modules.rent.accrual import RENT_DUE_TIME_NOT_SET, accrue

NOT_YET = "not-yet"


def run_pay_requests(session: Session, now: datetime) -> GenerationResult | str:
    """Accrue, then generate if it is past the pay request time. The caller owns the
    transaction."""
    settings = require_upi_settings(session, now)
    if clock.business_now(now).time() < settings.pay_request_time:
        return NOT_YET
    accrue(session, now=now)
    return generate_pay_requests(session, now=now)


def main() -> int:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    now = clock.utc_now()
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            result = run_pay_requests(session, now)
    except AppError as exc:
        if exc.code not in (UPI_ID_NOT_SET, RENT_DUE_TIME_NOT_SET):
            raise
        print(f"pay-requests refused: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    if isinstance(result, str):
        print("pay-requests: before the pay request time; nothing to do")
        return 0
    print(
        f"pay-requests: {result.created} created, {result.superseded} superseded, "
        f"{result.unchanged} unchanged"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
