"""Rule 4: staff choose which days a payment covers (docs/rent-and-payments.md §6; Q15, Q16;
D57 decisions 1 and 2)."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.payments.allocation import apply_credit, confirm_days, suggest_days
from app.modules.payments.approval import approve_payments
from app.modules.payments.models import PaymentAllocation
from app.modules.rent.accrual import accrue
from app.modules.rent.ledger import driver_position
from tests.payment_helpers import (
    AT_SIX_THU,
    another_driver,
    as_owner,
    as_staff,
    charges,
    items,
    record,
    world,
)
from tests.rent_helpers import ist, rupees


def test_the_suggestion_is_oldest_unpaid_first_and_allocates_nothing(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, c4, _ = charges(db, w.agreement.id)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(700))
    suggestion = suggest_days(db, payment, now=AT_SIX_THU)
    assert [(s.rent_charge_id, s.amount_paise) for s in suggestion] == [
        (c2.id, rupees(300)),
        (c3.id, rupees(300)),
        (c4.id, rupees(100)),
    ]
    assert db.scalars(select(PaymentAllocation)).all() == []


def test_confirm_writes_the_days_and_an_audit_entry(db: Session, test_settings: Settings) -> None:
    w = world(db)
    c2, c3, *_ = charges(db, w.agreement.id)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(600))
    confirm_days(
        db,
        as_staff(w.manager),
        payment.id,
        items((c2, rupees(300)), (c3, rupees(300))),
        now=AT_SIX_THU,
    )
    rows = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    ).all()
    assert sorted(r.amount_paise for r in rows) == [rupees(300), rupees(300)]
    assert all(r.confirmed_by == w.manager.id for r in rows)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "payment.days_confirmed")).one()


def test_re_confirming_replaces_the_days_without_deleting(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, *_ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    payment = record(db, test_settings, staff, w.driver, rupees(300))
    confirm_days(db, staff, payment.id, items((c2, rupees(300))), now=AT_SIX_THU)
    confirm_days(db, staff, payment.id, items((c3, rupees(300))), now=AT_SIX_THU)
    rows = db.scalars(
        select(PaymentAllocation)
        .where(PaymentAllocation.payment_id == payment.id)
        .order_by(PaymentAllocation.id)
    ).all()
    assert [(r.rent_charge_id, r.reversal_reason) for r in rows] == [
        (c2.id, "days re-confirmed"),
        (c3.id, None),
    ]


def test_allocating_to_another_drivers_day_is_refused(db: Session, test_settings: Settings) -> None:
    w = world(db)
    _, other_agreement = another_driver(db, w)
    accrue(db, now=AT_SIX_THU)
    other_day = charges(db, other_agreement.id)[0]
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(300))
    with pytest.raises(AppError) as exc:
        confirm_days(
            db, as_staff(w.manager), payment.id, items((other_day, rupees(300))), now=AT_SIX_THU
        )
    assert exc.value.code == "ALLOCATION_WRONG_DRIVER"


def test_allocating_to_a_future_day_is_refused(db: Session, test_settings: Settings) -> None:
    w = world(db)
    accrue(db, now=ist(date(2026, 11, 6), 9))  # a Friday charge exists, but "now" is Thursday
    friday_charge = charges(db, w.agreement.id)[-1]
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(300))
    with pytest.raises(AppError) as exc:
        confirm_days(
            db,
            as_staff(w.manager),
            payment.id,
            items((friday_charge, rupees(300))),
            now=AT_SIX_THU,
        )
    assert exc.value.code == "ALLOCATION_FUTURE_DAY"


def test_allocating_beyond_a_days_balance_is_refused(db: Session, test_settings: Settings) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(400))
    with pytest.raises(AppError) as exc:
        confirm_days(db, as_staff(w.manager), payment.id, items((c2, rupees(400))), now=AT_SIX_THU)
    assert exc.value.code == "ALLOCATION_EXCEEDS_DAY"


def test_pending_allocations_of_other_payments_count_against_the_day(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    first = record(db, test_settings, staff, w.driver, rupees(200))
    confirm_days(db, staff, first.id, items((c2, rupees(200))), now=AT_SIX_THU)
    second = record(db, test_settings, staff, w.driver, rupees(200))
    with pytest.raises(AppError) as exc:
        confirm_days(db, staff, second.id, items((c2, rupees(200))), now=AT_SIX_THU)
    assert exc.value.code == "ALLOCATION_EXCEEDS_DAY"


def test_allocating_beyond_the_unallocated_amount_is_refused(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, *_ = charges(db, w.agreement.id)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(500))
    with pytest.raises(AppError) as exc:
        confirm_days(
            db,
            as_staff(w.manager),
            payment.id,
            items((c2, rupees(300)), (c3, rupees(300))),
            now=AT_SIX_THU,
        )
    assert exc.value.code == "ALLOCATION_EXCEEDS_PAYMENT"


def test_the_same_day_twice_in_one_confirm_is_refused(db: Session, test_settings: Settings) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(300))
    with pytest.raises(AppError) as exc:
        confirm_days(
            db,
            as_staff(w.manager),
            payment.id,
            items((c2, rupees(100)), (c2, rupees(100))),
            now=AT_SIX_THU,
        )
    assert exc.value.code == "ALLOCATION_DUPLICATE_DAY"


def test_a_staff_member_who_is_not_the_manager_cannot_confirm_days(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    recorder = as_staff(w.other_staff)
    payment = record(db, test_settings, recorder, w.driver, rupees(300))
    with pytest.raises(AppError) as exc:
        confirm_days(db, recorder, payment.id, items((c2, rupees(300))), now=AT_SIX_THU)
    assert exc.value.status_code == 403
    assert exc.value.code == "DAYS_CONFIRM_NOT_ALLOWED"


def test_leftover_approved_credit_applied_later_counts_at_once(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, c4, _ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    payment = record(db, test_settings, staff, w.driver, rupees(500))
    confirm_days(db, staff, payment.id, items((c2, rupees(300))), now=AT_SIX_THU)
    approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == rupees(900)

    apply_credit(db, staff, payment.id, items((c3, rupees(200))), now=AT_SIX_THU)
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == rupees(700)
    assert db.scalars(select(AuditLog).where(AuditLog.action == "payment.credit_applied")).one()
    with pytest.raises(AppError) as exc:  # nothing left
        apply_credit(db, staff, payment.id, items((c4, rupees(100))), now=AT_SIX_THU)
    assert exc.value.code == "ALLOCATION_EXCEEDS_PAYMENT"


def test_credit_is_only_for_approved_payments_and_confirm_only_for_waiting_ones(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, *_ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    payment = record(db, test_settings, staff, w.driver, rupees(600))
    with pytest.raises(AppError) as exc:
        apply_credit(db, staff, payment.id, items((c2, rupees(300))), now=AT_SIX_THU)
    assert exc.value.code == "PAYMENT_NOT_APPROVED"
    confirm_days(db, staff, payment.id, items((c2, rupees(300))), now=AT_SIX_THU)
    approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    with pytest.raises(AppError) as exc:
        confirm_days(db, staff, payment.id, items((c3, rupees(300))), now=AT_SIX_THU)
    assert exc.value.code == "PAYMENT_NOT_AWAITING_APPROVAL"


def test_an_advance_deposit_is_never_allocated_to_days(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    deposit = record(
        db, test_settings, as_staff(w.manager), w.driver, rupees(2000), purpose="advance_deposit"
    )
    with pytest.raises(AppError) as exc:
        confirm_days(db, as_staff(w.manager), deposit.id, items((c2, rupees(300))), now=AT_SIX_THU)
    assert exc.value.code == "DEPOSIT_NOT_ALLOCATED"
