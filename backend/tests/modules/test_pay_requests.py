"""Pay request generation (docs/rent-and-payments.md §2; rule 18; N3, N4; D57)."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.errors import AppError
from app.modules.pay_requests.models import PayRequest
from app.modules.pay_requests.service import generate_pay_requests, mark_sent
from app.modules.rent.accrual import accrue
from tests.payment_helpers import (
    AT_SIX_THU,
    THU_5_NOV,
    as_staff,
    charges,
    world,
)
from tests.rent_helpers import (
    insert_approved_payment,
    ist,
    make_agreement,
    make_driver,
    make_vehicle,
    rupees,
)

FRI_6_NOV = date(2026, 11, 6)
MON_9_NOV = date(2026, 11, 9)


def _requests(db: Session, driver_id: int) -> list[PayRequest]:
    return list(
        db.scalars(
            select(PayRequest).where(PayRequest.driver_id == driver_id).order_by(PayRequest.id)
        )
    )


def test_generation_is_idempotent(db: Session) -> None:
    w = world(db)
    first = generate_pay_requests(db, now=AT_SIX_THU)
    second = generate_pay_requests(db, now=AT_SIX_THU)
    assert (first.created, second.created, second.unchanged) == (1, 0, 1)
    rows = _requests(db, w.driver.id)
    assert [r.status for r in rows] == ["open"]


def test_a_driver_without_an_active_agreement_gets_none(db: Session) -> None:
    w = world(db)
    draft_driver = make_driver(db, w.manager)
    make_agreement(db, draft_driver, make_vehicle(db), w.manager, start=THU_5_NOV)
    ended_driver = make_driver(db, w.manager)
    make_agreement(
        db,
        ended_driver,
        make_vehicle(db),
        w.manager,
        start=date(2026, 11, 2),
        end=date(2026, 11, 3),
        status="ended",
    )
    accrue(db, now=AT_SIX_THU)
    generate_pay_requests(db, now=AT_SIX_THU)
    assert _requests(db, draft_driver.id) == []
    assert _requests(db, ended_driver.id) == []
    assert len(_requests(db, w.driver.id)) == 1


def test_the_amount_equals_outstanding_up_to_the_period(db: Session) -> None:
    w = world(db)  # 2 to 5 Nov at ₹300 = ₹1,200
    c2, c3, c4, _ = charges(db, w.agreement.id)
    insert_approved_payment(
        db,
        w.driver,
        w.manager,
        [(c2, rupees(300)), (c3, rupees(300)), (c4, rupees(100))],
        received_on=THU_5_NOV,
    )
    generate_pay_requests(db, now=AT_SIX_THU)
    (request,) = _requests(db, w.driver.id)
    assert request.amount_paise == rupees(500)  # never more than the rent due (rule 18)
    assert (request.period_start, request.period_end) == (THU_5_NOV, THU_5_NOV)
    # Suggested days: oldest unpaid first (rule 4: only a suggestion).
    assert request.suggested_charge_ids == [c4.id, charges(db, w.agreement.id)[3].id]


def test_an_unapproved_payment_does_not_lower_the_amount(db: Session) -> None:
    w = world(db)
    c2, *_ = charges(db, w.agreement.id)
    insert_approved_payment(
        db,
        w.driver,
        w.manager,
        [(c2, rupees(300))],
        received_on=THU_5_NOV,
        status="awaiting_approval",
    )
    generate_pay_requests(db, now=AT_SIX_THU)
    (request,) = _requests(db, w.driver.id)
    assert request.amount_paise == rupees(1200)


def test_nothing_is_asked_when_nothing_is_due(db: Session) -> None:
    w = world(db)
    paid = [(c, rupees(300)) for c in charges(db, w.agreement.id)]
    insert_approved_payment(db, w.driver, w.manager, paid, received_on=THU_5_NOV)
    result = generate_pay_requests(db, now=AT_SIX_THU)
    assert result.created == 0
    assert _requests(db, w.driver.id) == []


def test_a_new_period_supersedes_the_old_request(db: Session) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    friday = ist(FRI_6_NOV, 8)
    accrue(db, now=friday)
    result = generate_pay_requests(db, now=friday)
    assert (result.created, result.superseded) == (1, 1)
    old, new = _requests(db, w.driver.id)
    assert old.status == "superseded"
    assert new.status == "open"
    assert new.period_start == FRI_6_NOV
    assert new.amount_paise == rupees(1500)


def test_the_reference_code_format(db: Session) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    (request,) = _requests(db, w.driver.id)
    digits = w.driver.code.removeprefix("D")
    assert request.reference_code == f"R{digits}1105"
    assert request.reference_code.isalnum()


def test_a_weekly_driver_gets_a_request_only_on_the_pay_day(db: Session) -> None:
    # Weekly pay day Monday; Monday 2 November start; Thursday is not a pay day.
    w = world(db, rhythm="weekly", weekly_pay_day=1)
    generate_pay_requests(db, now=AT_SIX_THU)
    assert _requests(db, w.driver.id) == []
    monday = ist(MON_9_NOV, 8)
    accrue(db, now=monday)
    generate_pay_requests(db, now=monday)
    (request,) = _requests(db, w.driver.id)
    assert request.period_start == MON_9_NOV - timedelta(days=6)
    assert request.period_end == MON_9_NOV
    assert request.amount_paise == rupees(300) * 8  # 2 to 9 November


def test_generation_needs_the_business_upi_id(db: Session) -> None:
    world(db, upi_id=None)
    with pytest.raises(AppError) as exc:
        generate_pay_requests(db, now=AT_SIX_THU)
    assert exc.value.code == "UPI_ID_NOT_SET"


def test_generation_writes_an_audit_entry_without_personal_data(db: Session) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "pay_request.created")).one()
    text = str(entry.after)
    assert w.driver.full_name not in text and w.driver.mobile not in text


def test_marking_sent_counts_each_tap(db: Session) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    (request,) = _requests(db, w.driver.id)
    manager = as_staff(w.manager)
    mark_sent(db, manager, request.id, now=AT_SIX_THU)
    mark_sent(db, manager, request.id, now=AT_SIX_THU + timedelta(minutes=5))
    db.refresh(request)
    assert request.send_count == 2
    assert request.sent_by == w.manager.id
    assert request.sent_at == AT_SIX_THU + timedelta(minutes=5)


def test_staff_who_cannot_see_the_drivers_money_cannot_send(db: Session) -> None:
    w = world(db)
    generate_pay_requests(db, now=AT_SIX_THU)
    (request,) = _requests(db, w.driver.id)
    with pytest.raises(AppError) as exc:
        mark_sent(db, as_staff(w.other_staff), request.id, now=AT_SIX_THU)
    assert exc.value.status_code == 404  # D54: records you may not see are 404
