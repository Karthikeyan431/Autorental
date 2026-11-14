"""The ledger formulas (docs/rent-and-payments.md §1; rules 3 and 13; Q3).

Day balance = charge + approved adjustments - allocations that are not reversed and belong to an
approved payment (or approved advance transaction). Outstanding = sum of day balances; overdue =
the balances whose due_at has passed (no grace period). Nothing is stored.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.payments.models import PaymentAllocation
from app.modules.rent.accrual import accrue
from app.modules.rent.ledger import (
    Position,
    driver_ledger,
    driver_position,
    overdue_list,
)
from app.modules.rent.models import ChargeAdjustment, RentCharge
from tests.rent_helpers import (
    insert_approved_payment,
    ist,
    make_agreement,
    make_driver,
    make_vehicle,
    rupees,
    scene,
)

MON_2_NOV = date(2026, 11, 2)
THU_5_NOV = date(2026, 11, 5)


def _charges(db: Session, agreement_id: int) -> list[RentCharge]:
    return list(
        db.scalars(
            select(RentCharge)
            .where(RentCharge.agreement_id == agreement_id)
            .order_by(RentCharge.rent_date)
        )
    )


def test_the_worked_example_reproduces_exactly(db: Session) -> None:
    s = scene(db)  # due time 10:00, same day
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    at_six = ist(THU_5_NOV, 18)
    accrue(db, now=at_six)
    c2, c3, c4, _ = _charges(db, agreement.id)
    insert_approved_payment(
        db,
        s.driver,
        s.staff,
        [(c2, rupees(300)), (c3, rupees(300)), (c4, rupees(100))],
        received_on=c4.rent_date,
    )

    ledger = driver_ledger(db, s.driver.id, now=at_six)

    rows = [
        (r.rent_date, r.charge_paise, r.allocated_paise, r.balance_paise, r.status, r.is_overdue)
        for r in ledger.rows
    ]
    assert rows == [
        (date(2026, 11, 2), 30_000, 30_000, 0, "paid", False),
        (date(2026, 11, 3), 30_000, 30_000, 0, "paid", False),
        (date(2026, 11, 4), 30_000, 10_000, 20_000, "part_paid", True),
        (date(2026, 11, 5), 30_000, 0, 30_000, "unpaid", True),
    ]
    assert ledger.rows[3].due_at == ist(THU_5_NOV, 10)
    assert ledger.totals.charge_paise == 120_000
    assert ledger.totals.allocated_paise == 70_000
    assert ledger.totals.balance_paise == 50_000
    assert ledger.outstanding_paise == 50_000
    assert ledger.overdue_paise == 50_000
    assert driver_position(db, s.driver.id, now=at_six) == Position(50_000, 50_000)


def test_before_approval_outstanding_is_1200_and_days_show_awaiting(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    at_six = ist(THU_5_NOV, 18)
    accrue(db, now=at_six)
    c2, c3, c4, _ = _charges(db, agreement.id)
    insert_approved_payment(
        db,
        s.driver,
        s.staff,
        [(c2, rupees(300)), (c3, rupees(300)), (c4, rupees(100))],
        received_on=c4.rent_date,
        status="awaiting_approval",
    )

    ledger = driver_ledger(db, s.driver.id, now=at_six)

    assert ledger.outstanding_paise == 120_000
    assert ledger.overdue_paise == 120_000  # N8: still overdue while awaiting approval
    assert [r.awaiting_approval_paise for r in ledger.rows] == [30_000, 30_000, 10_000, 0]
    assert [r.allocated_paise for r in ledger.rows] == [0, 0, 0, 0]


def test_a_rejected_or_reversed_allocation_never_counts(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    accrue(db, now=ist(MON_2_NOV, 18))
    (charge,) = _charges(db, agreement.id)
    insert_approved_payment(
        db, s.driver, s.staff, [(charge, rupees(300))], received_on=MON_2_NOV, status="rejected"
    )
    approved = insert_approved_payment(
        db, s.driver, s.staff, [(charge, rupees(300))], received_on=MON_2_NOV
    )
    allocation = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == approved.id)
    ).one()
    allocation.reversed_at = ist(MON_2_NOV, 19)
    allocation.reversed_by = s.staff.id
    allocation.reversal_reason = "Test reversal"
    db.flush()

    assert driver_position(db, s.driver.id, now=ist(MON_2_NOV, 20)) == Position(30_000, 30_000)


def test_no_grace_period_overdue_at_the_due_time(db: Session) -> None:
    s = scene(db)
    make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    accrue(db, now=ist(MON_2_NOV, 8))
    assert driver_position(db, s.driver.id, now=ist(MON_2_NOV, 10)) == Position(30_000, 0)
    assert driver_position(db, s.driver.id, now=ist(MON_2_NOV, 10, 1)) == Position(30_000, 30_000)


def test_a_weekly_driver_is_not_overdue_before_the_pay_day_and_is_after_its_due_time(
    db: Session,
) -> None:
    s = scene(db, rhythm="weekly", weekly_pay_day=7)
    # Wednesday 4 to Sunday 8 November 2026; pay day Sunday at 10:00.
    make_agreement(db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 4), status="active")
    accrue(db, now=ist(date(2026, 11, 6), 18))
    friday = driver_position(db, s.driver.id, now=ist(date(2026, 11, 6), 18))
    assert friday == Position(outstanding_paise=90_000, overdue_paise=0)

    accrue(db, now=ist(date(2026, 11, 8), 9))
    assert driver_position(db, s.driver.id, now=ist(date(2026, 11, 8), 10)).overdue_paise == 0
    sunday = driver_position(db, s.driver.id, now=ist(date(2026, 11, 8), 10, 1))
    assert sunday == Position(outstanding_paise=150_000, overdue_paise=150_000)


def test_switching_a_driver_to_weekly_does_not_make_old_days_not_overdue(db: Session) -> None:
    s = scene(db, weekly_pay_day=7)
    make_agreement(db, s.driver, s.vehicle, s.staff, start=date(2026, 11, 2), status="active")
    accrue(db, now=ist(date(2026, 11, 3), 12))
    assert driver_position(db, s.driver.id, now=ist(date(2026, 11, 3), 12)).overdue_paise == 60_000
    s.driver.payment_rhythm = "weekly"
    db.flush()
    accrue(db, now=ist(date(2026, 11, 4), 12))
    # 2 and 3 Nov keep their daily due times; 4 Nov is due on Sunday 8 Nov.
    assert driver_position(db, s.driver.id, now=ist(date(2026, 11, 4), 12)) == Position(
        90_000, 60_000
    )


def test_approved_adjustments_change_the_balance_and_pending_ones_do_not(db: Session) -> None:
    s = scene(db)
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    accrue(db, now=ist(date(2026, 11, 3), 12))
    c2, c3 = _charges(db, agreement.id)
    db.add_all(
        [
            ChargeAdjustment(
                rent_charge_id=c2.id,
                amount_paise=-30_000,
                reason="Test waiver",
                status="approved",
                requested_by=s.staff.id,
                decided_by=s.staff.id,
                decided_at=ist(date(2026, 11, 3), 11),
            ),
            ChargeAdjustment(
                rent_charge_id=c3.id,
                amount_paise=-30_000,
                reason="Test waiver",
                requested_by=s.staff.id,
            ),
        ]
    )
    db.flush()
    ledger = driver_ledger(db, s.driver.id, now=ist(date(2026, 11, 3), 12))
    assert [(r.status, r.balance_paise) for r in ledger.rows] == [
        ("waived", 0),
        ("unpaid", 30_000),
    ]
    assert [r.pending_adjustments_paise for r in ledger.rows] == [0, -30_000]
    assert ledger.outstanding_paise == 30_000


def test_the_date_filter_limits_rows_but_not_the_overall_position(db: Session) -> None:
    s = scene(db)
    make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    now = ist(THU_5_NOV, 18)
    accrue(db, now=now)
    ledger = driver_ledger(
        db, s.driver.id, now=now, date_from=date(2026, 11, 3), date_to=date(2026, 11, 4)
    )
    assert [r.rent_date for r in ledger.rows] == [date(2026, 11, 3), date(2026, 11, 4)]
    assert ledger.totals.charge_paise == 60_000
    assert ledger.outstanding_paise == 120_000


def test_the_ledger_covers_every_agreement_of_the_driver(db: Session) -> None:
    s = scene(db)
    make_agreement(
        db,
        s.driver,
        s.vehicle,
        s.staff,
        start=date(2026, 11, 1),
        end=date(2026, 11, 2),
        status="ended",
    )
    other = make_vehicle(db, status="rented")
    make_agreement(db, s.driver, other, s.staff, start=date(2026, 11, 4), status="active")
    accrue(db, now=ist(date(2026, 11, 4), 18))
    ledger = driver_ledger(db, s.driver.id, now=ist(date(2026, 11, 4), 18))
    assert [r.rent_date.day for r in ledger.rows] == [1, 2, 4]


def test_the_overdue_list_has_amount_oldest_date_and_days(db: Session) -> None:
    s = scene(db)
    make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    paid_up = make_driver(db, s.staff)
    second = make_vehicle(db, status="rented")
    paid_agreement = make_agreement(db, paid_up, second, s.staff, start=THU_5_NOV, status="active")
    now = ist(THU_5_NOV, 18)
    accrue(db, now=now)
    (paid_charge,) = _charges(db, paid_agreement.id)
    insert_approved_payment(
        db, paid_up, s.staff, [(paid_charge, rupees(300))], received_on=THU_5_NOV
    )

    rows = overdue_list(db, now=now)

    assert [
        (r.driver_id, r.overdue_paise, r.oldest_overdue_date, r.days_overdue) for r in rows
    ] == [(s.driver.id, 120_000, MON_2_NOV, 3)]
    assert rows[0].driver_code == s.driver.code
    assert rows[0].managed_by.id == s.staff.id


def test_the_overdue_list_can_be_limited_to_some_drivers(db: Session) -> None:
    s = scene(db)
    make_agreement(db, s.driver, s.vehicle, s.staff, start=MON_2_NOV, status="active")
    accrue(db, now=ist(THU_5_NOV, 18))
    assert overdue_list(db, now=ist(THU_5_NOV, 18), driver_ids=[]) == []
    assert len(overdue_list(db, now=ist(THU_5_NOV, 18), driver_ids=[s.driver.id])) == 1
