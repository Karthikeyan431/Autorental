"""Charge adjustments (Q11; rent-and-payments.md §7): staff request, the owner decides, only
approved ones count. A day's net charge never goes below 0 or below what is already allocated."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.rent.accrual import accrue
from app.modules.rent.adjustments import decide_adjustment, request_adjustment
from app.modules.rent.ledger import Position, driver_ledger, driver_position
from app.modules.rent.models import RentCharge
from app.modules.rent.schemas import AdjustmentCreate, AdjustmentDecision
from app.modules.users.models import User
from tests.modules.test_activation import staff_of
from tests.rent_helpers import (
    Scene,
    insert_approved_payment,
    ist,
    make_agreement,
    make_user,
    rupees,
    scene,
)

DAY = date(2026, 11, 2)
NOW = ist(date(2026, 11, 2), 18)


def owner_of(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        role="owner",
        must_change_password=False,
        permissions=frozenset(p.value for p in Permission),
        family_id="test-family",
    )


def _setup(db: Session) -> tuple[Scene, User, RentCharge]:
    s = scene(db)
    owner = make_user(db, role="owner")
    agreement = make_agreement(db, s.driver, s.vehicle, s.staff, start=DAY, status="active")
    accrue(db, now=NOW)
    charge = db.scalars(select(RentCharge).where(RentCharge.agreement_id == agreement.id)).one()
    return s, owner, charge


def _request(db: Session, s: Scene, charge: RentCharge, amount: int) -> int:
    adjustment = request_adjustment(
        db,
        staff_of(s.staff),
        charge.id,
        AdjustmentCreate(amount_paise=amount, reason="Auto off the road for repairs"),
        now=NOW,
    )
    return adjustment.id


def _decide(db: Session, owner: User, adjustment_id: int, decision: str) -> None:
    decide_adjustment(
        db,
        owner_of(owner),
        adjustment_id,
        AdjustmentDecision(decision=decision, reason="Checked"),  # type: ignore[arg-type]
        now=NOW,
    )


def test_an_approved_minus_300_waives_the_day(db: Session) -> None:
    s, owner, charge = _setup(db)
    adjustment_id = _request(db, s, charge, -rupees(300))
    _decide(db, owner, adjustment_id, "approve")
    assert driver_position(db, s.driver.id, now=NOW) == Position(0, 0)
    (row,) = driver_ledger(db, s.driver.id, now=NOW).rows
    assert (row.adjustments_paise, row.balance_paise, row.status) == (-30_000, 0, "waived")


def test_a_pending_adjustment_changes_nothing(db: Session) -> None:
    s, _, charge = _setup(db)
    _request(db, s, charge, -rupees(300))
    assert driver_position(db, s.driver.id, now=NOW) == Position(30_000, 30_000)


def test_a_rejected_adjustment_changes_nothing(db: Session) -> None:
    s, owner, charge = _setup(db)
    _decide(db, owner, _request(db, s, charge, -rupees(300)), "reject")
    assert driver_position(db, s.driver.id, now=NOW) == Position(30_000, 30_000)


def test_an_adjustment_can_also_add_to_a_charge(db: Session) -> None:
    s, owner, charge = _setup(db)
    _decide(db, owner, _request(db, s, charge, rupees(50)), "approve")
    assert driver_position(db, s.driver.id, now=NOW).outstanding_paise == 35_000


def test_an_adjustment_below_zero_is_refused_when_requested(db: Session) -> None:
    s, _, charge = _setup(db)
    with pytest.raises(AppError) as refused:
        _request(db, s, charge, -rupees(301))
    assert refused.value.code == "ADJUSTMENT_TOO_LARGE"


def test_a_second_waiver_of_the_same_day_is_refused_when_decided(db: Session) -> None:
    s, owner, charge = _setup(db)
    first = _request(db, s, charge, -rupees(300))
    second = _request(db, s, charge, -rupees(300))
    _decide(db, owner, first, "approve")
    with pytest.raises(AppError) as refused:
        _decide(db, owner, second, "approve")
    assert refused.value.code == "ADJUSTMENT_TOO_LARGE"
    assert driver_position(db, s.driver.id, now=NOW).outstanding_paise == 0


def test_a_waiver_cannot_go_below_what_is_already_allocated(db: Session) -> None:
    s, owner, charge = _setup(db)
    insert_approved_payment(db, s.driver, s.staff, [(charge, rupees(200))], received_on=DAY)
    with pytest.raises(AppError) as refused:
        _request(db, s, charge, -rupees(200))
    assert refused.value.code == "ADJUSTMENT_TOO_LARGE"
    _decide(db, owner, _request(db, s, charge, -rupees(100)), "approve")
    assert driver_position(db, s.driver.id, now=NOW) == Position(0, 0)


def test_a_decided_adjustment_cannot_be_decided_again(db: Session) -> None:
    s, owner, charge = _setup(db)
    adjustment_id = _request(db, s, charge, -rupees(300))
    _decide(db, owner, adjustment_id, "reject")
    with pytest.raises(AppError) as refused:
        _decide(db, owner, adjustment_id, "approve")
    assert refused.value.code == "ADJUSTMENT_ALREADY_DECIDED"


def test_request_and_decision_are_audited(db: Session) -> None:
    s, owner, charge = _setup(db)
    adjustment_id = _request(db, s, charge, -rupees(300))
    _decide(db, owner, adjustment_id, "approve")
    actions = [
        (e.action, e.actor_id)
        for e in db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "charge_adjustment", AuditLog.entity_id == adjustment_id)
            .order_by(AuditLog.id)
        )
    ]
    assert actions == [
        ("charge_adjustment.requested", s.staff.id),
        ("charge_adjustment.approved", owner.id),
    ]


def test_the_original_charge_stays(db: Session) -> None:
    s, owner, charge = _setup(db)
    _decide(db, owner, _request(db, s, charge, -rupees(300)), "approve")
    db.expire_all()
    assert db.get(RentCharge, charge.id).amount_paise == 30_000  # type: ignore[union-attr]
