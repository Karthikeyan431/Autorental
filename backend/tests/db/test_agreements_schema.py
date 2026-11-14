"""Rule 2 in the database itself: a second active agreement for the same driver or auto, or an
overlapping date range, is refused even when inserted directly in SQL (bypassing the service).
Also: one charge per agreement per day (rule 1) and the payment table constraints (D50)."""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db_grants import INSERT_ONLY_TABLES
from tests.rent_helpers import Scene, make_driver, make_vehicle, scene


@pytest.fixture
def s(db: Session) -> Iterator[Scene]:
    yield scene(db)


def _insert(
    db: Session,
    driver_id: int,
    vehicle_id: int,
    creator_id: int,
    *,
    status: str,
    start: date,
    end: date | None = None,
) -> None:
    db.execute(
        text(
            "INSERT INTO agreements (driver_id, vehicle_id, status, start_date, end_date, "
            "daily_rent_paise, terms_version, created_by, activated_at, ended_at) "
            "VALUES (:d, :v, :status, :start, :end, 30000, 'test', :c, "
            "CASE WHEN :status IN ('active', 'ended') THEN now() END, "
            "CASE WHEN :status = 'ended' THEN now() END)"
        ),
        {
            "d": driver_id,
            "v": vehicle_id,
            "c": creator_id,
            "status": status,
            "start": start,
            "end": end,
        },
    )


def _refused(db: Session, constraint: str, **kwargs: object) -> None:
    with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
        _insert(db, **kwargs)  # type: ignore[arg-type]


def test_a_second_active_agreement_for_the_same_driver_raises(db: Session, s: Scene) -> None:
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="active", start=date(2026, 11, 1))
    other = make_vehicle(db)
    # The first range is open-ended, so both the unique index and the exclusion constraint apply.
    _refused(
        db,
        "one_active_agreement_per_driver|no_driver_overlap",
        driver_id=s.driver.id,
        vehicle_id=other.id,
        creator_id=s.staff.id,
        status="active",
        start=date(2026, 12, 1),
    )


def test_a_second_active_agreement_for_the_same_vehicle_raises(db: Session, s: Scene) -> None:
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="active", start=date(2026, 11, 1))
    other = make_driver(db, s.staff)
    _refused(
        db,
        "one_active_agreement_per_vehicle|no_vehicle_overlap",
        driver_id=other.id,
        vehicle_id=s.vehicle.id,
        creator_id=s.staff.id,
        status="active",
        start=date(2026, 12, 1),
    )


def test_the_partial_unique_index_alone_refuses_two_active_rows(db: Session, s: Scene) -> None:
    # Non-overlapping ranges, so only the partial unique index can refuse the second row.
    _insert(
        db,
        s.driver.id,
        s.vehicle.id,
        s.staff.id,
        status="active",
        start=date(2026, 11, 1),
        end=date(2026, 11, 10),
    )
    _refused(
        db,
        "one_active_agreement_per_driver",
        driver_id=s.driver.id,
        vehicle_id=make_vehicle(db).id,
        creator_id=s.staff.id,
        status="active",
        start=date(2027, 1, 1),
    )


def test_overlapping_ranges_raise_for_the_driver(db: Session, s: Scene) -> None:
    _insert(
        db,
        s.driver.id,
        s.vehicle.id,
        s.staff.id,
        status="ended",
        start=date(2026, 11, 1),
        end=date(2026, 11, 10),
    )
    _refused(
        db,
        "no_driver_overlap",
        driver_id=s.driver.id,
        vehicle_id=make_vehicle(db).id,
        creator_id=s.staff.id,
        status="ended",
        start=date(2026, 11, 5),
        end=date(2026, 11, 20),
    )


def test_overlapping_ranges_raise_for_the_vehicle(db: Session, s: Scene) -> None:
    _insert(
        db,
        s.driver.id,
        s.vehicle.id,
        s.staff.id,
        status="ended",
        start=date(2026, 11, 1),
        end=date(2026, 11, 10),
    )
    _refused(
        db,
        "no_vehicle_overlap",
        driver_id=make_driver(db, s.staff).id,
        vehicle_id=s.vehicle.id,
        creator_id=s.staff.id,
        status="active",
        start=date(2026, 11, 10),  # Q1: the return day itself is refused ([] ranges)
    )


def test_the_day_after_the_return_day_is_allowed(db: Session, s: Scene) -> None:
    _insert(
        db,
        s.driver.id,
        s.vehicle.id,
        s.staff.id,
        status="ended",
        start=date(2026, 11, 1),
        end=date(2026, 11, 10),
    )
    _insert(
        db,
        make_driver(db, s.staff).id,
        s.vehicle.id,
        s.staff.id,
        status="active",
        start=date(2026, 11, 11),
    )


def test_drafts_and_cancelled_agreements_never_block(db: Session, s: Scene) -> None:
    for status in ("draft", "draft", "cancelled"):
        _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status=status, start=date(2026, 11, 1))
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="active", start=date(2026, 11, 1))


def test_one_charge_per_agreement_per_day(db: Session, s: Scene) -> None:
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="active", start=date(2026, 11, 1))
    agreement_id = db.scalar(text("SELECT max(id) FROM agreements"))
    insert = text(
        "INSERT INTO rent_charges (agreement_id, driver_id, rent_date, amount_paise, due_at, "
        "settings_version_id) VALUES (:a, :d, '2026-11-01', 30000, now(), :v)"
    )
    params = {"a": agreement_id, "d": s.driver.id, "v": s.settings.id}
    db.execute(insert, params)
    with pytest.raises(IntegrityError, match="one_charge_per_day"), db.begin_nested():
        db.execute(insert, params)


def test_rent_charges_is_registered_insert_only() -> None:
    assert "rent_charges" in INSERT_ONLY_TABLES


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        ("UPDATE agreements SET daily_rent_paise = 0", "daily_rent_positive"),
        ("UPDATE agreements SET end_date = start_date - 1", "end_after_start"),
    ],
)
def test_agreement_checks(db: Session, s: Scene, sql: str, constraint: str) -> None:
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="draft", start=date(2026, 11, 1))
    with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
        db.execute(text(sql))


def test_payment_allocation_needs_exactly_one_source(db: Session, s: Scene) -> None:
    _insert(db, s.driver.id, s.vehicle.id, s.staff.id, status="active", start=date(2026, 11, 1))
    db.execute(
        text(
            "INSERT INTO rent_charges (agreement_id, driver_id, rent_date, amount_paise, due_at, "
            "settings_version_id) SELECT max(id), :d, '2026-11-01', 30000, now(), :v "
            "FROM agreements"
        ),
        {"d": s.driver.id, "v": s.settings.id},
    )
    with pytest.raises(IntegrityError, match="one_source"), db.begin_nested():
        db.execute(
            text(
                "INSERT INTO payment_allocations (rent_charge_id, amount_paise, confirmed_by, "
                "confirmed_at) SELECT max(id), 100, :u, now() FROM rent_charges"
            ),
            {"u": s.staff.id},
        )


def test_the_same_upi_reference_cannot_be_recorded_twice(db: Session, s: Scene) -> None:
    insert = text(
        "INSERT INTO payments (driver_id, amount_paise, method, source, reference, received_on, "
        "recorded_by, status) VALUES (:d, 100, 'upi', 'upi_direct', 'TESTUTR0001', "
        "'2026-11-01', :u, :status)"
    )
    # Week 6 (0008): a rejected payment records who rejected it, when and why.
    rejected = text(
        "INSERT INTO payments (driver_id, amount_paise, method, source, reference, received_on, "
        "recorded_by, status, rejected_by, rejected_at, rejection_reason) VALUES (:d, 100, "
        "'upi', 'upi_direct', 'TESTUTR0001', '2026-11-01', :u, 'rejected', :u, now(), 'Test')"
    )
    params = {"d": s.driver.id, "u": s.staff.id}
    db.execute(rejected, params)  # a rejected one releases it
    db.execute(insert, {**params, "status": "awaiting_approval"})
    with pytest.raises(IntegrityError, match="unique_payment_reference"), db.begin_nested():
        db.execute(insert, {**params, "status": "awaiting_approval"})
