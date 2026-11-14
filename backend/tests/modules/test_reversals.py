"""Reversals (Q4; rule 11): staff request, the owner decides; allocations are reversed, never
deleted, and the receipt is marked cancelled."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.pay_requests.models import PayRequest
from app.modules.pay_requests.service import generate_pay_requests
from app.modules.payments.allocation import confirm_days
from app.modules.payments.approval import approve_payments
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.payments.reversals import decide_reversal, request_reversal
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


def _approved(db: Session, test_settings: Settings) -> tuple[Payment, World]:
    w = world(db)
    all_days = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    payment = record(db, test_settings, staff, w.driver, rupees(1200))
    confirm_days(
        db, staff, payment.id, items(*[(c, rupees(300)) for c in all_days]), now=AT_SIX_THU
    )
    approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    db.refresh(payment)
    return payment, w


def test_a_reversal_restores_day_balances_cancels_the_receipt_and_is_audited(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _approved(db, test_settings)
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == 0
    receipt_no = payment.receipt_no
    request = request_reversal(
        db, as_staff(w.manager), payment.id, "Recorded twice by mistake", now=AT_SIX_THU
    )
    assert request.decision is None
    # Nothing changes while the request waits.
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == 0

    decide_reversal(db, as_owner(w.owner), request.id, "approved", None, now=AT_SIX_THU)
    db.refresh(payment)
    assert payment.status == "reversed"
    assert payment.receipt_no == receipt_no  # the number is kept, marked cancelled
    assert payment.receipt_cancelled_at is not None
    rows = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    ).all()
    assert len(rows) == 4 and all(r.reversed_at is not None for r in rows)
    position = driver_position(db, w.driver.id, now=AT_SIX_THU)
    assert (position.outstanding_paise, position.overdue_paise) == (rupees(1200), rupees(1200))
    assert db.scalars(
        select(AuditLog).where(
            AuditLog.action == "payment.reversed", AuditLog.entity_id == payment.id
        )
    ).one()


def test_staff_cannot_decide_a_reversal(db: Session, test_settings: Settings) -> None:
    payment, w = _approved(db, test_settings)
    request = request_reversal(
        db, as_staff(w.manager), payment.id, "Recorded twice by mistake", now=AT_SIX_THU
    )
    with pytest.raises(AppError) as exc:
        decide_reversal(db, as_staff(w.manager), request.id, "approved", None, now=AT_SIX_THU)
    assert exc.value.status_code == 403


def test_a_rejected_reversal_changes_nothing(db: Session, test_settings: Settings) -> None:
    payment, w = _approved(db, test_settings)
    request = request_reversal(
        db, as_staff(w.manager), payment.id, "Recorded twice by mistake", now=AT_SIX_THU
    )
    decide_reversal(
        db, as_owner(w.owner), request.id, "rejected", "The payment is right", now=AT_SIX_THU
    )
    db.refresh(payment)
    assert payment.status == "approved" and payment.receipt_cancelled_at is None
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == 0


def test_only_approved_payments_can_be_reversed_and_one_request_at_a_time(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _approved(db, test_settings)
    staff = as_staff(w.manager)
    request_reversal(db, staff, payment.id, "Recorded twice by mistake", now=AT_SIX_THU)
    with pytest.raises(AppError) as exc:
        request_reversal(db, staff, payment.id, "Asking again", now=AT_SIX_THU)
    assert exc.value.code == "REVERSAL_ALREADY_REQUESTED"
    waiting = record(db, test_settings, staff, w.driver, rupees(300))
    with pytest.raises(AppError) as exc:
        request_reversal(db, staff, waiting.id, "Not approved yet", now=AT_SIX_THU)
    assert exc.value.code == "PAYMENT_NOT_APPROVED"


def test_a_reversal_reopens_the_paid_pay_request(db: Session, test_settings: Settings) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    staff = as_staff(w.manager)
    owner = as_owner(w.owner)
    all_days = charges(db, w.agreement.id)
    payment = record(db, test_settings, staff, w.driver, rupees(1200))
    confirm_days(
        db, staff, payment.id, items(*[(c, rupees(300)) for c in all_days]), now=AT_SIX_THU
    )
    approve_payments(db, owner, [payment.id], now=AT_SIX_THU)
    request = db.scalars(select(PayRequest).where(PayRequest.driver_id == w.driver.id)).one()
    assert request.status == "paid"
    reversal = request_reversal(db, staff, payment.id, "Wrong driver", now=AT_SIX_THU)
    decide_reversal(db, owner, reversal.id, "approved", None, now=AT_SIX_THU)
    db.refresh(request)
    assert request.status == "open"
