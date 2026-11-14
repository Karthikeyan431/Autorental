"""Charge adjustments (Q11; docs/rent-and-payments.md §7).

* Staff with `adjustments.request` ask for a signed amount with a reason (negative = waiver);
  the owner (`adjustments.decide`, never grantable) approves or rejects. Only approved ones
  count. The original charge never changes (rule 11).
* A day's net charge (charge + approved adjustments) may never fall below what approved payments
  already cover, nor below 0: ADJUSTMENT_TOO_LARGE, checked when requested and again when
  approved (another adjustment may have been approved in between).
* rent_charges is insert-only, so the app role cannot lock its rows (FOR UPDATE needs UPDATE
  privilege). The agreement row is locked instead: every change to one agreement's days runs
  one at a time (D53).
"""

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser
from app.modules.agreements.models import Agreement
from app.modules.drivers.access import not_found
from app.modules.drivers.models import Driver
from app.modules.drivers.service import user_refs
from app.modules.rent.access import require_money_view
from app.modules.rent.ledger import charge_figures
from app.modules.rent.models import ChargeAdjustment, RentCharge
from app.modules.rent.schemas import AdjustmentCreate, AdjustmentDecision, AdjustmentOut

REASON_LATE_RETURN = "Returned on {day}, recorded late"


def lock_agreement(session: Session, agreement_id: int) -> Agreement:
    agreement = session.scalars(
        select(Agreement)
        .where(Agreement.id == agreement_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if agreement is None:
        raise not_found()
    return agreement


def _charge(session: Session, charge_id: int) -> RentCharge:
    charge = session.get(RentCharge, charge_id)
    if charge is None:
        raise not_found()
    return charge


def _too_large() -> AppError:
    return AppError(
        "ADJUSTMENT_TOO_LARGE",
        "This would take the day below what it costs or below what is already paid.",
    )


def _check_fits(session: Session, charge: RentCharge, amount: int, now: datetime) -> None:
    figures = charge_figures(now)
    row = session.execute(
        select(figures.c.adjustments, figures.c.allocated).where(figures.c.charge_id == charge.id)
    ).one_or_none()
    adjustments, allocated = (int(row[0]), int(row[1])) if row is not None else (0, 0)
    if charge.amount_paise + adjustments + amount < max(allocated, 0):
        raise _too_large()


def add_adjustment(
    session: Session,
    charge: RentCharge,
    *,
    amount: int,
    reason: str,
    requested_by: int | None,
    now: datetime,
    ip: str | None,
    check: bool = True,
) -> ChargeAdjustment:
    """Insert a pending adjustment and its audit entry. The caller holds the agreement lock."""
    if check:
        _check_fits(session, charge, amount, now)
    adjustment = ChargeAdjustment(
        rent_charge_id=charge.id, amount_paise=amount, reason=reason, requested_by=requested_by
    )
    session.add(adjustment)
    session.flush()
    write_audit(
        session,
        action="charge_adjustment.requested",
        entity_type="charge_adjustment",
        entity_id=adjustment.id,
        actor_id=requested_by,
        after={
            "rent_charge_id": charge.id,
            "driver_id": charge.driver_id,
            "rent_date": charge.rent_date,
            "amount_paise": amount,
        },
        reason=reason,
        ip=ip,
    )
    return adjustment


def request_adjustment(
    session: Session,
    user: CurrentUser,
    charge_id: int,
    data: AdjustmentCreate,
    *,
    now: datetime | None = None,
    ip: str | None = None,
) -> ChargeAdjustment:
    moment = now or clock.utc_now()
    charge = _charge(session, charge_id)
    driver = session.get(Driver, charge.driver_id)
    if driver is None:
        raise not_found()
    require_money_view(user, driver)
    lock_agreement(session, charge.agreement_id)
    return add_adjustment(
        session,
        charge,
        amount=data.amount_paise,
        reason=data.reason,
        requested_by=user.id,
        now=moment,
        ip=ip,
    )


def decide_adjustment(
    session: Session,
    user: CurrentUser,
    adjustment_id: int,
    data: AdjustmentDecision,
    *,
    now: datetime | None = None,
    ip: str | None = None,
) -> ChargeAdjustment:
    moment = now or clock.utc_now()
    adjustment = session.get(ChargeAdjustment, adjustment_id)
    if adjustment is None:
        raise not_found()
    charge = _charge(session, adjustment.rent_charge_id)
    lock_agreement(session, charge.agreement_id)
    adjustment = session.scalars(
        select(ChargeAdjustment)
        .where(ChargeAdjustment.id == adjustment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if adjustment.status != "pending":
        raise AppError(
            "ADJUSTMENT_ALREADY_DECIDED",
            "This adjustment has already been decided.",
            details={"status": adjustment.status},
        )
    if data.decision == "approve":
        _check_fits(session, charge, adjustment.amount_paise, moment)
    adjustment.status = "approved" if data.decision == "approve" else "rejected"
    adjustment.decided_by = user.id
    adjustment.decided_at = moment
    adjustment.decision_reason = data.reason
    session.flush()
    write_audit(
        session,
        action=f"charge_adjustment.{adjustment.status}",
        entity_type="charge_adjustment",
        entity_id=adjustment.id,
        actor_id=user.id,
        before={"status": "pending"},
        after={
            "status": adjustment.status,
            "rent_charge_id": charge.id,
            "driver_id": charge.driver_id,
            "amount_paise": adjustment.amount_paise,
        },
        reason=data.reason,
        ip=ip,
    )
    if adjustment.status == "approved":
        # D57 decision 4: a waiver can clear what a pay request asks for.
        from app.modules.pay_requests.service import refresh_pay_request_status

        refresh_pay_request_status(session, charge.driver_id, now=moment, actor_id=user.id)
    return adjustment


def adjustments_out(session: Session, adjustments: list[ChargeAdjustment]) -> list[AdjustmentOut]:
    charges = {
        c.id: c
        for c in session.scalars(
            select(RentCharge).where(RentCharge.id.in_([a.rent_charge_id for a in adjustments]))
        )
    }
    refs = user_refs(
        session, [a.requested_by for a in adjustments] + [a.decided_by for a in adjustments]
    )
    return [
        AdjustmentOut(
            id=a.id,
            rent_charge_id=a.rent_charge_id,
            rent_date=charges[a.rent_charge_id].rent_date,
            driver_id=charges[a.rent_charge_id].driver_id,
            amount_paise=a.amount_paise,
            reason=a.reason,
            status=a.status,
            requested_by=refs.get(a.requested_by) if a.requested_by else None,
            created_at=a.created_at,
            decided_by=refs.get(a.decided_by) if a.decided_by else None,
            decided_at=a.decided_at,
            decision_reason=a.decision_reason,
        )
        for a in adjustments
    ]


def pending_adjustments(
    session: Session, *, driver_ids: list[int] | None = None
) -> list[ChargeAdjustment]:
    query = (
        select(ChargeAdjustment)
        .join(RentCharge, RentCharge.id == ChargeAdjustment.rent_charge_id)
        .where(ChargeAdjustment.status == "pending")
        .order_by(ChargeAdjustment.created_at, ChargeAdjustment.id)
    )
    if driver_ids is not None:
        query = query.where(RentCharge.driver_id.in_(driver_ids))
    return list(session.scalars(query))


def count_pending(session: Session, *, driver_ids: list[int] | None = None) -> int:
    query = (
        select(func.count())
        .select_from(ChargeAdjustment)
        .join(RentCharge, RentCharge.id == ChargeAdjustment.rent_charge_id)
        .where(ChargeAdjustment.status == "pending")
    )
    if driver_ids is not None:
        if not driver_ids:
            return 0
        query = query.where(RentCharge.driver_id.in_(driver_ids))
    return int(session.scalar(query) or 0)


def late_return_reason(day: date) -> str:
    return REASON_LATE_RETURN.format(day=f"{day.day} {day:%b %Y}")
