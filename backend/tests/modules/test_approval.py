"""Rule 13: every payment counts only after the owner approves it (docs/rent-and-payments.md §5;
N7, N8; D57)."""

import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.pay_requests.models import PayRequest
from app.modules.pay_requests.service import generate_pay_requests, open_request
from app.modules.payments.allocation import confirm_days
from app.modules.payments.approval import approve_payments, reject_payment
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.payments.receipts import financial_year
from app.modules.rent.adjustments import decide_adjustment, request_adjustment
from app.modules.rent.ledger import driver_ledger, driver_position
from app.modules.rent.schemas import AdjustmentCreate, AdjustmentDecision
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

RECEIPT = re.compile(r"^RCPT/2026-27/\d{6}$")


def _worked_example(db: Session, test_settings: Settings) -> tuple[Payment, World]:
    """docs/rent-and-payments.md §1: ₹700 cash confirmed as 2 Nov ₹300, 3 Nov ₹300, 4 Nov ₹100."""
    w = world(db)
    c2, c3, c4, _ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    payment = record(db, test_settings, staff, w.driver, rupees(700))
    confirm_days(
        db,
        staff,
        payment.id,
        items((c2, rupees(300)), (c3, rupees(300)), (c4, rupees(100))),
        now=AT_SIX_THU,
    )
    return payment, w


def test_an_unapproved_payment_never_reduces_outstanding_or_overdue(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _worked_example(db, test_settings)
    position = driver_position(db, w.driver.id, now=AT_SIX_THU)
    assert position.outstanding_paise == rupees(1200)
    assert position.overdue_paise == rupees(1200)
    ledger = driver_ledger(db, w.driver.id, now=AT_SIX_THU)
    # N8: shown as "payment awaiting approval", still unpaid and overdue.
    assert [r.awaiting_approval_paise for r in ledger.rows] == [
        rupees(300),
        rupees(300),
        rupees(100),
        0,
    ]
    assert all(r.is_overdue for r in ledger.rows)
    assert payment.receipt_no is None


def test_after_approval_it_counts_exactly_as_the_worked_example(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _worked_example(db, test_settings)
    (result,) = approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    assert result.outcome == "approved"
    db.refresh(payment)
    assert payment.status == "approved"
    assert payment.approved_by == w.owner.id
    position = driver_position(db, w.driver.id, now=AT_SIX_THU)
    assert (position.outstanding_paise, position.overdue_paise) == (rupees(500), rupees(500))
    ledger = driver_ledger(db, w.driver.id, now=AT_SIX_THU)
    assert [r.status for r in ledger.rows] == ["paid", "paid", "part_paid", "unpaid"]


def test_the_receipt_number_is_issued_at_approval_and_only_then(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _worked_example(db, test_settings)
    assert payment.receipt_no is None
    (result,) = approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    db.refresh(payment)
    assert payment.receipt_no is not None and RECEIPT.fullmatch(payment.receipt_no)
    assert result.receipt_no == payment.receipt_no
    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "payment.approved", AuditLog.entity_id == payment.id
        )
    ).one()
    assert entry.actor_id == w.owner.id


def test_a_rejected_payment_never_counts_and_its_days_are_marked_not_deleted(
    db: Session, test_settings: Settings
) -> None:
    payment, w = _worked_example(db, test_settings)
    reject_payment(db, as_owner(w.owner), payment.id, "Cash not found in the box", now=AT_SIX_THU)
    db.refresh(payment)
    assert payment.status == "rejected"
    assert payment.receipt_no is None
    assert payment.rejection_reason == "Cash not found in the box"
    rows = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    ).all()
    assert len(rows) == 3
    assert {r.reversal_reason for r in rows} == {"payment rejected"}
    assert all(r.reversed_at is not None and r.reversed_by == w.owner.id for r in rows)
    position = driver_position(db, w.driver.id, now=AT_SIX_THU)
    assert position.outstanding_paise == rupees(1200)
    # A rejected payment can never be approved afterwards.
    (result,) = approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    assert result.outcome == "refused"
    assert result.code == "PAYMENT_NOT_AWAITING_APPROVAL"


def test_reject_needs_the_owner(db: Session, test_settings: Settings) -> None:
    payment, w = _worked_example(db, test_settings)
    with pytest.raises(AppError) as exc:
        reject_payment(db, as_staff(w.manager), payment.id, "Not mine to decide", now=AT_SIX_THU)
    assert exc.value.status_code == 403


def test_approve_many_refuses_one_by_one_and_approves_the_rest(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    c2, c3, *_ = charges(db, w.agreement.id)
    staff = as_staff(w.manager)
    owner = as_owner(w.owner)
    first = record(db, test_settings, staff, w.driver, rupees(300))
    confirm_days(db, staff, first.id, items((c2, rupees(300))), now=AT_SIX_THU)
    second = record(db, test_settings, staff, w.driver, rupees(300))
    confirm_days(db, staff, second.id, items((c3, rupees(300))), now=AT_SIX_THU)
    # The owner waives ₹300 of 3 Nov: the second payment no longer fits that day.
    adjustment = request_adjustment(
        db,
        staff,
        c3.id,
        AdjustmentCreate(amount_paise=-rupees(300), reason="Auto in repair"),
        now=AT_SIX_THU,
    )
    decide_adjustment(
        db, owner, adjustment.id, AdjustmentDecision(decision="approve"), now=AT_SIX_THU
    )
    results = approve_payments(db, owner, [second.id, first.id], now=AT_SIX_THU)
    outcomes = {r.payment_id: (r.outcome, r.code) for r in results}
    assert outcomes[first.id] == ("approved", None)
    assert outcomes[second.id] == ("refused", "PAYMENT_NO_LONGER_FITS")


def test_a_payment_without_days_can_be_approved_as_credit(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    payment = record(db, test_settings, as_staff(w.other_staff), w.driver, rupees(300))
    (result,) = approve_payments(db, as_owner(w.owner), [payment.id], now=AT_SIX_THU)
    assert result.outcome == "approved"
    # Q15: unallocated credit does not lower outstanding until staff apply it to days.
    assert driver_position(db, w.driver.id, now=AT_SIX_THU).outstanding_paise == rupees(1200)


def test_the_pay_request_is_paid_when_outstanding_through_its_period_reaches_zero(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    request = open_request(db, w.driver.id)
    assert request is not None
    staff = as_staff(w.manager)
    owner = as_owner(w.owner)
    all_days = charges(db, w.agreement.id)
    part = record(db, test_settings, staff, w.driver, rupees(900))
    confirm_days(
        db, staff, part.id, items(*[(c, rupees(300)) for c in all_days[:3]]), now=AT_SIX_THU
    )
    approve_payments(db, owner, [part.id], now=AT_SIX_THU)
    db.refresh(request)
    assert request.status == "open"
    rest = record(db, test_settings, staff, w.driver, rupees(300))
    confirm_days(db, staff, rest.id, items((all_days[3], rupees(300))), now=AT_SIX_THU)
    approve_payments(db, owner, [rest.id], now=AT_SIX_THU)
    db.refresh(request)
    assert request.status == "paid"


def test_a_waiver_that_clears_the_balance_marks_the_request_paid(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    owner = as_owner(w.owner)
    all_days = charges(db, w.agreement.id)
    paid = record(db, test_settings, staff, w.driver, rupees(900))
    confirm_days(
        db, staff, paid.id, items(*[(c, rupees(300)) for c in all_days[:3]]), now=AT_SIX_THU
    )
    approve_payments(db, owner, [paid.id], now=AT_SIX_THU)
    generate_pay_requests(db, now=AT_SIX_THU)
    request = db.scalars(select(PayRequest).where(PayRequest.driver_id == w.driver.id)).one()
    assert request.amount_paise == rupees(300)
    adjustment = request_adjustment(
        db,
        staff,
        all_days[3].id,
        AdjustmentCreate(amount_paise=-rupees(300), reason="Auto in repair"),
        now=AT_SIX_THU,
    )
    decide_adjustment(
        db, owner, adjustment.id, AdjustmentDecision(decision="approve"), now=AT_SIX_THU
    )
    db.refresh(request)
    assert request.status == "paid"


def test_financial_years_run_april_to_march() -> None:
    from datetime import date

    assert financial_year(date(2026, 11, 14)) == "2026-27"
    assert financial_year(date(2027, 3, 31)) == "2026-27"
    assert financial_year(date(2027, 4, 1)) == "2027-28"
    assert financial_year(date(2099, 12, 1)) == "2099-00"
