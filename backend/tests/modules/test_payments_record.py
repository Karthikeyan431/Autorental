"""Recording a payment (docs/rent-and-payments.md §3; N6; Q4; D57 decision 1)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.pay_requests.service import generate_pay_requests, open_request
from app.modules.payments.approval import approve_payments, reject_payment
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.payments.reversals import decide_reversal, request_reversal
from app.modules.payments.schemas import PaymentCreate
from app.modules.payments.service import record_payment
from tests.payment_helpers import (
    AT_SIX_THU,
    THU_5_NOV,
    as_owner,
    as_staff,
    record,
    world,
)
from tests.rent_helpers import rupees


def test_any_staff_member_can_record_for_any_driver(db: Session, test_settings: Settings) -> None:
    w = world(db)
    payment = record(db, test_settings, as_staff(w.other_staff), w.driver, rupees(300))
    assert payment.status == "awaiting_approval"
    assert payment.recorded_by == w.other_staff.id
    assert payment.proof_document_id is not None
    assert payment.source == "cash_office"


def test_a_payment_needs_a_proof_photo(db: Session, test_settings: Settings) -> None:
    w = world(db)
    data = PaymentCreate(
        driver_id=w.driver.id,
        amount_paise=rupees(300),
        method="cash",
        received_on=THU_5_NOV,
        idempotency_key="test-key-no-proof",
    )
    with pytest.raises(AppError) as exc:
        record_payment(db, test_settings, as_staff(w.manager), data, proof=None, now=AT_SIX_THU)
    assert exc.value.code == "PROOF_REQUIRED"


def test_a_upi_payment_needs_a_reference(db: Session, test_settings: Settings) -> None:
    w = world(db)
    with pytest.raises(AppError) as exc:
        record(db, test_settings, as_staff(w.manager), w.driver, rupees(300), method="upi")
    assert exc.value.code == "REFERENCE_REQUIRED"


def test_a_duplicate_upi_reference_is_refused(db: Session, test_settings: Settings) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    record(db, test_settings, staff, w.driver, rupees(300), method="upi", reference="UTR 6001 0001")
    with pytest.raises(AppError) as exc:
        record(
            db, test_settings, staff, w.driver, rupees(300), method="upi", reference="utr60010001"
        )
    assert exc.value.code == "DUPLICATE_REFERENCE"


def test_a_rejected_payment_releases_its_reference(db: Session, test_settings: Settings) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    first = record(
        db, test_settings, staff, w.driver, rupees(300), method="upi", reference="UTR60010002"
    )
    reject_payment(db, as_owner(w.owner), first.id, "Wrong amount typed", now=AT_SIX_THU)
    again = record(
        db, test_settings, staff, w.driver, rupees(200), method="upi", reference="UTR60010002"
    )
    assert again.id != first.id


def test_a_reversed_payment_releases_its_reference(db: Session, test_settings: Settings) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    owner = as_owner(w.owner)
    first = record(
        db, test_settings, staff, w.driver, rupees(300), method="upi", reference="UTR60010003"
    )
    approve_payments(db, owner, [first.id], now=AT_SIX_THU)
    reversal = request_reversal(
        db, staff, first.id, "Recorded for the wrong driver", now=AT_SIX_THU
    )
    decide_reversal(db, owner, reversal.id, "approved", None, now=AT_SIX_THU)
    again = record(
        db, test_settings, staff, w.driver, rupees(300), method="upi", reference="UTR60010003"
    )
    assert again.status == "awaiting_approval"


def test_a_double_submit_with_the_same_key_creates_one_payment(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    first = record(db, test_settings, staff, w.driver, rupees(300), key="test-key-double-tap")
    second = record(db, test_settings, staff, w.driver, rupees(300), key="test-key-double-tap")
    assert first.id == second.id
    count = db.scalar(
        select(func.count()).select_from(Payment).where(Payment.driver_id == w.driver.id)
    )
    assert count == 1


def test_reusing_a_key_for_a_different_payment_is_refused(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    staff = as_staff(w.manager)
    record(db, test_settings, staff, w.driver, rupees(300), key="test-key-reused-1")
    with pytest.raises(AppError) as exc:
        record(db, test_settings, staff, w.driver, rupees(400), key="test-key-reused-1")
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_recording_creates_no_allocation(db: Session, test_settings: Settings) -> None:
    w = world(db)
    payment = record(db, test_settings, as_staff(w.manager), w.driver, rupees(700))
    allocations = db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
    ).all()
    assert allocations == []


def test_a_payment_cannot_be_received_in_the_future(db: Session, test_settings: Settings) -> None:
    w = world(db)
    with pytest.raises(AppError) as exc:
        record(
            db,
            test_settings,
            as_staff(w.manager),
            w.driver,
            rupees(300),
            received_on=THU_5_NOV + timedelta(days=1),
        )
    assert exc.value.code == "RECEIVED_DATE_IN_FUTURE"


def test_the_open_pay_request_is_linked(db: Session, test_settings: Settings) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    request = open_request(db, w.driver.id)
    assert request is not None
    payment = record(db, test_settings, as_staff(w.other_staff), w.driver, rupees(300))
    assert payment.pay_request_id == request.id
