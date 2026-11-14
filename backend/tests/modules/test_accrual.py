"""Rules 1 and 3 (docs/rent-and-payments.md §1): one charge per calendar day, Sundays and holidays
included; idempotent catch-up; each charge keeps the due time and rhythm in force when it was
created; weekly drivers are due on the first `weekly_pay_day` on or after the rent date (N3)."""

from datetime import date, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.time import iso_weekday
from app.modules.drivers.models import Driver
from app.modules.rent.accrual import accrue, compute_due_at
from app.modules.rent.models import RentCharge
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User
from app.modules.vehicles.models import Vehicle
from tests.rent_helpers import (
    days,
    ist,
    make_agreement,
    make_driver,
    make_settings_version,
    make_user,
    make_vehicle,
    rupees,
    scene,
)


def _charges(db: Session, agreement_id: int) -> list[RentCharge]:
    return list(
        db.scalars(
            select(RentCharge)
            .where(RentCharge.agreement_id == agreement_id)
            .order_by(RentCharge.rent_date)
        )
    )


def test_four_days_including_a_sunday_give_four_charges_and_1200(db: Session) -> None:
    s = scene(db)
    # Thursday 5 November 2026 to Sunday 8 November 2026.
    start = date(2026, 11, 5)
    assert iso_weekday(date(2026, 11, 8)) == 7
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=start, status="active")

    result = accrue(db, now=ist(date(2026, 11, 8), 9))

    charges = _charges(db, agreement.id)
    assert [c.rent_date for c in charges] == days(start, 4)
    assert sum(c.amount_paise for c in charges) == 120_000
    assert result.charges_created == 4


def test_a_public_holiday_is_charged(db: Session) -> None:
    s = scene(db)
    # Republic Day, Tuesday 26 January 2027: a national holiday, still a rent day.
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2027, 1, 25), status="active"
    )
    accrue(db, now=ist(date(2027, 1, 27), 9))
    assert date(2027, 1, 26) in [c.rent_date for c in _charges(db, agreement.id)]


def test_1_to_30_november_2026_gives_30_charges(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db,
        s.driver,
        s.vehicle,
        s.staff,
        start=date(2026, 11, 1),
        end=date(2026, 11, 30),
        status="ended",
    )
    accrue(db, now=ist(date(2026, 12, 15), 9))
    charges = _charges(db, agreement.id)
    assert len(charges) == 30
    assert sum(c.amount_paise for c in charges) == 30 * rupees(300)


def test_february_2028_gives_29_charges(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db,
        s.driver,
        s.vehicle,
        s.staff,
        start=date(2028, 2, 1),
        end=date(2028, 2, 29),
        status="ended",
    )
    accrue(db, now=ist(date(2028, 3, 1), 9))
    assert len(_charges(db, agreement.id)) == 29


def test_running_twice_creates_no_duplicates(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="active"
    )
    now = ist(date(2026, 11, 5), 9)
    first = accrue(db, now=now)
    second = accrue(db, now=now)
    assert first.charges_created == 4
    assert second.charges_created == 0
    assert len(_charges(db, agreement.id)) == 4


def test_three_days_of_downtime_are_filled_in_one_run(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 2), 9))
    assert len(_charges(db, agreement.id)) == 1
    # The server was down on 3, 4 and 5 November; it comes back on the 5th.
    result = accrue(db, now=ist(date(2026, 11, 5), 9))
    assert result.charges_created == 3
    assert [c.rent_date for c in _charges(db, agreement.id)] == days(date(2026, 11, 2), 4)


def test_no_charge_before_the_start_date_or_after_today(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 10), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 9), 23, 59))
    assert _charges(db, agreement.id) == []
    accrue(db, now=ist(date(2026, 11, 10), 0, 1))
    assert [c.rent_date for c in _charges(db, agreement.id)] == [date(2026, 11, 10)]


def test_business_date_is_kolkata_not_utc(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 10), status="active"
    )
    # 00:30 IST on 10 November is still 9 November in UTC; the 10th is already a rent day.
    accrue(db, now=ist(date(2026, 11, 10), 0, 30))
    assert len(_charges(db, agreement.id)) == 1


def test_draft_and_cancelled_agreements_are_never_charged(db: Session) -> None:
    s = scene(db)
    draft = make_agreement(db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2))
    cancelled = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="cancelled"
    )
    accrue(db, now=ist(date(2026, 11, 5), 9))
    assert _charges(db, draft.id) == []
    assert _charges(db, cancelled.id) == []


def test_an_ended_agreement_gets_no_charges_after_its_end_date(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db,
        s.driver,
        s.vehicle,
        s.staff,
        start=date(2026, 11, 2),
        end=date(2026, 11, 4),
        status="ended",
    )
    accrue(db, now=ist(date(2026, 11, 8), 9))
    # Q2: the return day is charged in full; nothing after it.
    assert [c.rent_date for c in _charges(db, agreement.id)] == days(date(2026, 11, 2), 3)


def test_each_charge_copies_the_agreement_rate_and_snapshots_settings(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), rent=rupees(275), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 2), 9))
    (charge,) = _charges(db, agreement.id)
    assert charge.amount_paise == 27_500
    assert charge.driver_id == s.driver.id
    assert charge.settings_version_id == s.settings.id
    assert charge.due_at == ist(date(2026, 11, 2), 10)


def test_changing_the_due_time_keeps_existing_due_at_and_tomorrow_uses_the_new_time(
    db: Session,
) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="active"
    )
    today = date(2026, 11, 5)
    accrue(db, now=ist(today, 9))
    before = {c.rent_date: (c.due_at, c.settings_version_id) for c in _charges(db, agreement.id)}

    # The owner moves the due time to 11:30 at 13:00 today.
    v2 = make_settings_version(db, due_time=time(11, 30), effective_from=ist(today, 13))
    accrue(db, now=ist(today, 14))
    accrue(db, now=ist(date(2026, 11, 6), 9))

    charges = {c.rent_date: c for c in _charges(db, agreement.id)}
    for rent_date, (due, version_id) in before.items():
        assert (charges[rent_date].due_at, charges[rent_date].settings_version_id) == (
            due,
            version_id,
        )
    assert charges[today].due_at == ist(today, 10)
    tomorrow = charges[date(2026, 11, 6)]
    assert tomorrow.due_at == ist(date(2026, 11, 6), 11, 30)
    assert tomorrow.settings_version_id == v2.id


def test_rent_charges_are_insert_only_for_the_app(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 2), 9))
    (charge,) = _charges(db, agreement.id)
    charge.amount_paise = 1
    with pytest.raises(Exception, match="permission denied"):
        db.flush()


# --- Rent due time not set (D20) -------------------------------------------------------------


def _no_settings_scene(db: Session) -> tuple[User, Driver, Vehicle]:
    staff = make_user(db)
    return staff, make_driver(db, staff), make_vehicle(db)


def test_accrual_refuses_without_a_rent_due_time_and_writes_nothing(db: Session) -> None:
    staff, driver, vehicle = _no_settings_scene(db)
    agreement = make_agreement(db, driver, vehicle, staff, start=date(2026, 11, 2), status="active")
    # The only settings version starts in the future, so none is in force now.
    make_settings_version(db, effective_from=ist(date(2027, 1, 1)))
    with pytest.raises(AppError) as refused:
        accrue(db, now=ist(date(2026, 11, 5), 9))
    assert refused.value.code == "RENT_DUE_TIME_NOT_SET"
    assert refused.value.message == "Set the rent due time in Settings"
    assert _charges(db, agreement.id) == []


def test_accrual_works_once_the_owner_sets_the_due_time(db: Session) -> None:
    assert db.scalar(select(func.count()).select_from(SettingsVersion)) == 0
    staff, driver, vehicle = _no_settings_scene(db)
    agreement = make_agreement(db, driver, vehicle, staff, start=date(2026, 11, 2), status="active")
    with pytest.raises(AppError):
        accrue(db, now=ist(date(2026, 11, 3), 9))
    make_settings_version(db, effective_from=ist(date(2026, 11, 3), 9, 30))
    accrue(db, now=ist(date(2026, 11, 3), 10))
    assert len(_charges(db, agreement.id)) == 2


# --- Weekly drivers (N3) ----------------------------------------------------------------------


def test_weekly_pay_day_7_is_sunday_never_monday(db: Session) -> None:
    s = scene(db, rhythm="weekly", weekly_pay_day=7)
    # Wednesday 4 November 2026 to Monday 9 November 2026.
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 4), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 9), 9))
    due = {c.rent_date: c.due_at for c in _charges(db, agreement.id)}
    sunday = date(2026, 11, 8)
    assert iso_weekday(sunday) == 7
    for rent_date in days(date(2026, 11, 4), 5):  # Wed to Sun: due Sunday 8 Nov at 10:00
        assert due[rent_date] == ist(sunday, 10)
    # Monday's rent is due the following Sunday, never on Monday itself.
    assert due[date(2026, 11, 9)] == ist(date(2026, 11, 15), 10)


@pytest.mark.parametrize(
    ("rent_date", "pay_day", "expected"),
    [
        (date(2026, 11, 2), 1, date(2026, 11, 2)),  # Monday, pay day Monday: same day
        (date(2026, 11, 3), 1, date(2026, 11, 9)),  # Tuesday: next Monday
        (date(2026, 11, 8), 1, date(2026, 11, 9)),  # Sunday: next day
        (date(2026, 11, 8), 7, date(2026, 11, 8)),  # Sunday, pay day Sunday: same day
        (date(2026, 11, 2), 5, date(2026, 11, 6)),  # Monday, pay day Friday
    ],
)
def test_weekly_due_date_is_the_first_pay_day_on_or_after_the_rent_date(
    db: Session, rent_date: date, pay_day: int, expected: date
) -> None:
    version = make_settings_version(db, weekly_pay_day=pay_day)
    assert compute_due_at(rent_date, rhythm="weekly", settings=version) == ist(expected, 10)
    assert compute_due_at(rent_date, rhythm="daily", settings=version) == ist(rent_date, 10)


def test_weekly_due_date_counts_from_the_due_day_offset(db: Session) -> None:
    version = make_settings_version(db, weekly_pay_day=1, due_day_offset=1)
    # Sunday 8 Nov + 1 day = Monday 9 Nov, which is the pay day.
    assert compute_due_at(date(2026, 11, 8), rhythm="weekly", settings=version) == ist(
        date(2026, 11, 9), 10
    )
    assert compute_due_at(date(2026, 11, 8), rhythm="daily", settings=version) == ist(
        date(2026, 11, 9), 10
    )


def test_switching_rhythm_keeps_existing_due_at(db: Session) -> None:
    s = scene(db, rhythm="weekly", weekly_pay_day=7)
    agreement = make_agreement(
        db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 4), status="active"
    )
    accrue(db, now=ist(date(2026, 11, 5), 9))
    before = {c.rent_date: c.due_at for c in _charges(db, agreement.id)}

    s.driver.payment_rhythm = "daily"
    db.flush()
    accrue(db, now=ist(date(2026, 11, 6), 9))

    charges = {c.rent_date: c.due_at for c in _charges(db, agreement.id)}
    assert {d: charges[d] for d in before} == before
    assert charges[date(2026, 11, 6)] == ist(date(2026, 11, 6), 10)
