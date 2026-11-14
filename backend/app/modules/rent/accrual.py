"""Daily rent accrual (rules 1 and 3; docs/rent-and-payments.md §1).

For every active or ended agreement, create one charge for each date from `start_date` to today
(or `end_date`) that has none yet. There is no weekday or holiday logic, so Sundays and holidays
are charged by construction. Each charge copies the agreement's rate and stores `due_at`
computed from the settings version in force *now*, and the driver's payment rhythm *now*; later
changes affect only charges created afterwards.

Idempotent: the unique constraint on (agreement_id, rent_date) plus ON CONFLICT DO NOTHING
makes re-runs and overlapping runs harmless, and one run fills every day missed during
downtime. The agreement rows are locked while their charges are written, so ending an agreement
and accruing it never interleave (an end date recorded late sees every charge to waive, D52).

D20: while no settings version is in force, nothing is written and RENT_DUE_TIME_NOT_SET is
raised (the CLI exits non-zero with the same message).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.time import business_date, due_at, iso_weekday
from app.modules.agreements.models import Agreement
from app.modules.drivers.models import Driver
from app.modules.rent.models import RentCharge
from app.modules.settings.models import SettingsVersion
from app.modules.settings.service import get_current_settings

RENT_DUE_TIME_NOT_SET = "RENT_DUE_TIME_NOT_SET"
RENT_DUE_TIME_MESSAGE = "Set the rent due time in Settings"


@dataclass(frozen=True)
class AccrualResult:
    charges_created: int
    agreements: int


def rent_due_time_not_set() -> AppError:
    return AppError(RENT_DUE_TIME_NOT_SET, RENT_DUE_TIME_MESSAGE, status_code=409)


def require_rent_settings(session: Session, now: datetime) -> SettingsVersion:
    """The settings version in force at `now`, or RENT_DUE_TIME_NOT_SET (D20). The first version
    cannot be saved without a rent due time, so "no version" means "not set"."""
    current = get_current_settings(session, now)
    if current is None:
        raise rent_due_time_not_set()
    return current


def compute_due_at(rent_date: date, *, rhythm: str, settings: SettingsVersion) -> datetime:
    """When a day's rent is due, in UTC.

    Daily: `rent_date + due_day_offset` at `rent_due_time` (Asia/Kolkata).
    Weekly (N3): the first `weekly_pay_day` (ISO, 1 = Monday ... 7 = Sunday) on or after
    `rent_date + due_day_offset`, at `rent_due_time`.
    """
    base = rent_date + timedelta(days=settings.due_day_offset)
    if rhythm == "weekly":
        base += timedelta(days=(settings.weekly_pay_day - iso_weekday(base)) % 7)
    return due_at(base, settings.rent_due_time)


def _missing_dates(session: Session, agreement: Agreement, last_day: date) -> list[date]:
    existing = set(
        session.scalars(
            select(RentCharge.rent_date).where(
                RentCharge.agreement_id == agreement.id,
                RentCharge.rent_date >= agreement.start_date,
                RentCharge.rent_date <= last_day,
            )
        )
    )
    span = (last_day - agreement.start_date).days + 1
    every_day = (agreement.start_date + timedelta(days=i) for i in range(span))
    return [day for day in every_day if day not in existing]


def accrue(
    session: Session, *, now: datetime | None = None, actor_id: int | None = None
) -> AccrualResult:
    """Create every missing charge up to today. The caller owns the transaction."""
    moment = now or clock.utc_now()
    settings = require_rent_settings(session, moment)
    today = business_date(moment)

    # Only agreements that can still be missing a day: the number of charges is below the number
    # of days from the start date to today (or the end date).
    last_day = func.least(func.coalesce(Agreement.end_date, today), today)
    charge_count = (
        select(func.count())
        .where(RentCharge.agreement_id == Agreement.id)
        .correlate(Agreement)
        .scalar_subquery()
    )
    agreements = session.scalars(
        select(Agreement)
        .where(
            Agreement.status.in_(("active", "ended")),
            Agreement.start_date <= today,
            charge_count < (last_day - Agreement.start_date + 1),
        )
        .order_by(Agreement.id)
        .with_for_update(of=Agreement)
        .execution_options(populate_existing=True)
    ).all()

    created = 0
    touched = 0
    for agreement in agreements:
        if agreement.status not in ("active", "ended"):
            continue  # changed while we waited for the lock
        end = min(agreement.end_date or today, today)
        missing = _missing_dates(session, agreement, end)
        if not missing:
            continue
        rhythm = session.scalar(
            select(Driver.payment_rhythm).where(Driver.id == agreement.driver_id)
        )
        rows = [
            {
                "agreement_id": agreement.id,
                "driver_id": agreement.driver_id,
                "rent_date": day,
                "amount_paise": agreement.daily_rent_paise,
                "due_at": compute_due_at(day, rhythm=rhythm or "daily", settings=settings),
                "settings_version_id": settings.id,
            }
            for day in missing
        ]
        result = session.execute(
            insert(RentCharge)
            .values(rows)
            .on_conflict_do_nothing(constraint="one_charge_per_day")
            .returning(RentCharge.id)
        )
        inserted = len(result.all())
        if inserted:
            created += inserted
            touched += 1

    if created:
        # One entry per run that changed something, so the 15-minute timer does not flood the
        # audit log with empty runs. Counts only.
        write_audit(
            session,
            action="rent.accrued",
            entity_type="rent_accrual",
            actor_id=actor_id,
            after={
                "charges_created": created,
                "agreements": touched,
                "through": today,
                "settings_version_id": settings.id,
            },
        )
    session.flush()
    return AccrualResult(charges_created=created, agreements=touched)
