"""Rule 5: the owner controls advance adjustments (docs/rent-and-payments.md §7; Q5, Q14)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.payments.advance import (
    advance_balance,
    decide_advance,
    request_advance_adjustment,
    request_refund,
)
from app.modules.payments.approval import approve_payments
from app.modules.payments.models import AdvanceTransaction, PaymentAllocation
from app.modules.rent.ledger import driver_position
from tests.payment_helpers import (
    AT_SIX_THU,
    World,
    as_owner,
    as_staff,
    charges,
    items,
    record,
    world,
)
from tests.rent_helpers import rupees


def _with_deposit(
    db: Session,
    test_settings: Settings,
    amount: int = rupees(500),
    *,
    advance_adjustments_enabled: bool = True,
) -> World:
    w = world(db, advance_adjustments_enabled=advance_adjustments_enabled)
    deposit = record(
        db, test_settings, as_staff(w.manager), w.driver, amount, purpose="advance_deposit"
    )
    assert advance_balance(db, w.driver.id) == 0  # a deposit needs approval too
    approve_payments(db, as_owner(w.owner), [deposit.id], now=AT_SIX_THU)
    assert advance_balance(db, w.driver.id) == amount
    return w


def test_a_pending_adjustment_changes_nothing(db: Session, test_settings: Settings) -> None:
    w = _with_deposit(db, test_settings)
    c2, *_ = charges(db, w.agreement.id)
    request_advance_adjustment(
        db,
        as_staff(w.manager),
        w.driver.id,
        items((c2, rupees(300))),
        "Use the deposit",
        now=AT_SIX_THU,
    )
    assert advance_balance(db, w.driver.id) == rupees(500)
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == rupees(1200)


def test_an_approved_adjustment_pays_the_days_and_lowers_the_balance(
    db: Session, test_settings: Settings
) -> None:
    w = _with_deposit(db, test_settings)
    c2, *_ = charges(db, w.agreement.id)
    tx = request_advance_adjustment(
        db,
        as_staff(w.manager),
        w.driver.id,
        items((c2, rupees(300))),
        "Use the deposit",
        now=AT_SIX_THU,
    )
    assert tx.amount_paise == -rupees(300)
    decide_advance(db, as_owner(w.owner), tx.id, "approved", None, now=AT_SIX_THU)
    assert advance_balance(db, w.driver.id) == rupees(200)
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == rupees(900)


def test_a_rejected_adjustment_marks_its_days_reversed(
    db: Session, test_settings: Settings
) -> None:
    w = _with_deposit(db, test_settings)
    c2, *_ = charges(db, w.agreement.id)
    tx = request_advance_adjustment(
        db,
        as_staff(w.manager),
        w.driver.id,
        items((c2, rupees(300))),
        "Use the deposit",
        now=AT_SIX_THU,
    )
    decide_advance(db, as_owner(w.owner), tx.id, "rejected", "Keep the deposit", now=AT_SIX_THU)
    rows = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.advance_transaction_id == tx.id)
    ).all()
    assert [r.reversal_reason for r in rows] == ["advance adjustment rejected"]
    assert advance_balance(db, w.driver.id) == rupees(500)


def test_an_adjustment_above_the_balance_is_refused(db: Session, test_settings: Settings) -> None:
    w = _with_deposit(db, test_settings, rupees(200))
    c2, *_ = charges(db, w.agreement.id)
    with pytest.raises(AppError) as exc:
        request_advance_adjustment(
            db,
            as_staff(w.manager),
            w.driver.id,
            items((c2, rupees(300))),
            "Use the deposit",
            now=AT_SIX_THU,
        )
    assert exc.value.code == "ADVANCE_INSUFFICIENT"


def test_pending_adjustments_together_cannot_exceed_the_balance(
    db: Session, test_settings: Settings
) -> None:
    w = _with_deposit(db, test_settings, rupees(400))
    c2, c3, *_ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    request_advance_adjustment(
        db, staff, w.driver.id, items((c2, rupees(300))), "Use the deposit", now=AT_SIX_THU
    )
    with pytest.raises(AppError) as exc:
        request_advance_adjustment(
            db, staff, w.driver.id, items((c3, rupees(300))), "Use the rest", now=AT_SIX_THU
        )
    assert exc.value.code == "ADVANCE_INSUFFICIENT"


def test_the_balance_never_goes_below_zero_in_the_database(
    db: Session, test_settings: Settings
) -> None:
    w = _with_deposit(db, test_settings, rupees(100))
    db.add(
        AdvanceTransaction(
            driver_id=w.driver.id,
            kind="adjustment",
            amount_paise=-rupees(200),
            status="approved",
            approved_by=w.owner.id,
            approved_at=AT_SIX_THU,
            reason="Direct write that skips the service",
        )
    )
    db.flush()
    with pytest.raises(IntegrityError):
        db.execute(text("SET CONSTRAINTS advance_balance_not_negative IMMEDIATE"))


def test_adjustments_are_refused_while_switched_off(db: Session, test_settings: Settings) -> None:
    w = _with_deposit(db, test_settings, advance_adjustments_enabled=False)
    c2, *_ = charges(db, w.agreement.id)
    with pytest.raises(AppError) as exc:
        request_advance_adjustment(
            db,
            as_staff(w.manager),
            w.driver.id,
            items((c2, rupees(300))),
            "Use the deposit",
            now=AT_SIX_THU,
        )
    assert exc.value.code == "ADVANCE_ADJUSTMENTS_OFF"


def test_refunds_are_refused_while_switched_off(db: Session, test_settings: Settings) -> None:
    w = _with_deposit(db, test_settings)
    with pytest.raises(AppError) as exc:
        request_refund(
            db, as_staff(w.manager), w.driver.id, rupees(100), "Driver leaving", now=AT_SIX_THU
        )
    assert exc.value.code == "REFUNDS_DISABLED"


def test_staff_cannot_decide_advance(db: Session, test_settings: Settings) -> None:
    w = _with_deposit(db, test_settings)
    c2, *_ = charges(db, w.agreement.id)
    tx = request_advance_adjustment(
        db,
        as_staff(w.manager),
        w.driver.id,
        items((c2, rupees(300))),
        "Use the deposit",
        now=AT_SIX_THU,
    )
    with pytest.raises(AppError) as exc:
        decide_advance(db, as_staff(w.manager), tx.id, "approved", None, now=AT_SIX_THU)
    assert exc.value.status_code == 403
