"""Daily rent accrual, once (docs/rent-and-payments.md §1):

    python -m app.jobs.accrue

Idempotent: it creates every missing charge up to today and nothing else, so running it every
15 minutes (production: a systemd timer, Week 8; development: APScheduler or by hand) is safe
and fills any days missed while the server was down.

D20: while no rent due time is set it writes nothing, prints "Set the rent due time in
Settings" to stderr and exits 1. Output names counts only, never personal data.
"""

import sys

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.modules.rent.accrual import RENT_DUE_TIME_NOT_SET, accrue


def main() -> int:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            result = accrue(session)
    except AppError as exc:
        if exc.code != RENT_DUE_TIME_NOT_SET:
            raise
        print(f"rent-accrual refused: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(
        f"rent-accrual: {result.charges_created} charges created for {result.agreements} agreements"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
