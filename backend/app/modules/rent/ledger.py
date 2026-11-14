"""Ledger queries (docs/rent-and-payments.md §1 "Formulas"). Nothing here is stored.

* Day balance = charge + approved adjustments - allocations that are not reversed and belong to
  an approved payment or an approved advance transaction (rules 13 and 5; Q11).
* Outstanding as of now = sum of day balances of the days already charged.
* Overdue = sum of positive day balances whose `due_at` has passed (Q3: no grace period).
* Awaiting approval for a day = allocations from payments still `awaiting_approval`: shown,
  never subtracted (N8).
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, NamedTuple

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.time import business_date
from app.modules.agreements.models import Agreement
from app.modules.drivers.models import Driver
from app.modules.drivers.schemas import UserRef
from app.modules.payments.models import AdvanceTransaction, Payment, PaymentAllocation
from app.modules.rent.models import ChargeAdjustment, RentCharge
from app.modules.rent.schemas import (
    DayStatus,
    LedgerOut,
    LedgerRow,
    LedgerTotals,
    OverdueRow,
)
from app.modules.users.models import User


class Position(NamedTuple):
    outstanding_paise: int
    overdue_paise: int


def _zero(value: Any) -> Any:
    return func.coalesce(value, 0)


def _adjustment_totals() -> Any:
    approved = ChargeAdjustment.status == "approved"
    pending = ChargeAdjustment.status == "pending"
    return (
        select(
            ChargeAdjustment.rent_charge_id.label("charge_id"),
            func.sum(case((approved, ChargeAdjustment.amount_paise), else_=0)).label("approved"),
            func.sum(case((pending, ChargeAdjustment.amount_paise), else_=0)).label("pending"),
            func.array_agg(ChargeAdjustment.id).filter(pending).label("pending_ids"),
        )
        .group_by(ChargeAdjustment.rent_charge_id)
        .subquery("adj")
    )


def _allocation_totals() -> Any:
    counts = or_(Payment.status == "approved", AdvanceTransaction.status == "approved")
    awaiting = Payment.status == "awaiting_approval"
    return (
        select(
            PaymentAllocation.rent_charge_id.label("charge_id"),
            func.sum(case((counts, PaymentAllocation.amount_paise), else_=0)).label("allocated"),
            func.sum(case((awaiting, PaymentAllocation.amount_paise), else_=0)).label("awaiting"),
        )
        .outerjoin(Payment, Payment.id == PaymentAllocation.payment_id)
        .outerjoin(
            AdvanceTransaction,
            AdvanceTransaction.id == PaymentAllocation.advance_transaction_id,
        )
        .where(PaymentAllocation.reversed_at.is_(None))
        .group_by(PaymentAllocation.rent_charge_id)
        .subquery("alloc")
    )


def charge_figures(now: datetime) -> Any:
    """One row per charge already accrued by `now`, with every figure of the formulas."""
    adj = _adjustment_totals()
    alloc = _allocation_totals()
    adjustments = _zero(adj.c.approved)
    allocated = _zero(alloc.c.allocated)
    balance = RentCharge.amount_paise + adjustments - allocated
    return (
        select(
            RentCharge.id.label("charge_id"),
            RentCharge.agreement_id,
            RentCharge.driver_id,
            RentCharge.rent_date,
            RentCharge.due_at,
            RentCharge.amount_paise.label("charge"),
            adjustments.label("adjustments"),
            _zero(adj.c.pending).label("pending"),
            adj.c.pending_ids,
            allocated.label("allocated"),
            _zero(alloc.c.awaiting).label("awaiting"),
            balance.label("balance"),
            and_(balance > 0, RentCharge.due_at < now).label("is_overdue"),
        )
        .outerjoin(adj, adj.c.charge_id == RentCharge.id)
        .outerjoin(alloc, alloc.c.charge_id == RentCharge.id)
        .where(RentCharge.rent_date <= business_date(now))
        .subquery("figures")
    )


def _status(charge: int, adjustments: int, allocated: int, balance: int) -> DayStatus:
    if balance <= 0:
        return "waived" if allocated == 0 and charge + adjustments <= 0 else "paid"
    return "part_paid" if allocated > 0 else "unpaid"


def _position_query(figures: Any) -> Select[Any]:
    return select(
        _zero(func.sum(figures.c.balance)),
        _zero(func.sum(case((figures.c.is_overdue, figures.c.balance), else_=0))),
    )


def driver_position(session: Session, driver_id: int, *, now: datetime) -> Position:
    figures = charge_figures(now)
    outstanding, overdue = session.execute(
        _position_query(figures).where(figures.c.driver_id == driver_id)
    ).one()
    return Position(int(outstanding), int(overdue))


def driver_ledger(
    session: Session,
    driver_id: int,
    *,
    now: datetime,
    date_from: date | None = None,
    date_to: date | None = None,
) -> LedgerOut:
    figures = charge_figures(now)
    query = (
        select(figures, Agreement.agreement_no)
        .join(Agreement, Agreement.id == figures.c.agreement_id)
        .where(figures.c.driver_id == driver_id)
        .order_by(figures.c.rent_date, figures.c.charge_id)
    )
    if date_from is not None:
        query = query.where(figures.c.rent_date >= date_from)
    if date_to is not None:
        query = query.where(figures.c.rent_date <= date_to)
    rows = [
        LedgerRow(
            charge_id=r.charge_id,
            agreement_id=r.agreement_id,
            agreement_no=r.agreement_no,
            rent_date=r.rent_date,
            due_at=r.due_at,
            charge_paise=r.charge,
            adjustments_paise=int(r.adjustments),
            pending_adjustments_paise=int(r.pending),
            allocated_paise=int(r.allocated),
            awaiting_approval_paise=int(r.awaiting),
            balance_paise=int(r.balance),
            status=_status(r.charge, int(r.adjustments), int(r.allocated), int(r.balance)),
            is_overdue=bool(r.is_overdue),
            pending_adjustment_ids=sorted(r.pending_ids or []),
        )
        for r in session.execute(query)
    ]
    position = driver_position(session, driver_id, now=now)
    return LedgerOut(
        driver_id=driver_id,
        as_of=now,
        rows=rows,
        totals=LedgerTotals(
            charge_paise=sum(r.charge_paise for r in rows),
            adjustments_paise=sum(r.adjustments_paise for r in rows),
            allocated_paise=sum(r.allocated_paise for r in rows),
            balance_paise=sum(r.balance_paise for r in rows),
        ),
        outstanding_paise=position.outstanding_paise,
        overdue_paise=position.overdue_paise,
    )


def overdue_list(
    session: Session, *, now: datetime, driver_ids: Sequence[int] | None = None
) -> list[OverdueRow]:
    """The missed-rent list: drivers whose overdue is above 0, oldest first."""
    if driver_ids is not None and not driver_ids:
        return []
    figures = charge_figures(now)
    overdue = func.sum(case((figures.c.is_overdue, figures.c.balance), else_=0))
    oldest = func.min(case((figures.c.is_overdue, figures.c.rent_date)))
    grouped = (
        select(
            figures.c.driver_id,
            overdue.label("overdue"),
            func.sum(figures.c.balance).label("outstanding"),
            func.sum(figures.c.awaiting).label("awaiting"),
            oldest.label("oldest"),
        )
        .group_by(figures.c.driver_id)
        .having(overdue > 0)
    )
    if driver_ids is not None:
        grouped = grouped.where(figures.c.driver_id.in_(list(driver_ids)))
    sub = grouped.subquery("overdue")
    query = (
        select(sub, Driver.code, Driver.full_name, Driver.managed_by, User.name.label("manager"))
        .join(Driver, Driver.id == sub.c.driver_id)
        .join(User, User.id == Driver.managed_by)
        .order_by(sub.c.oldest, sub.c.overdue.desc(), Driver.code)
    )
    today = business_date(now)
    return [
        OverdueRow(
            driver_id=r.driver_id,
            driver_code=r.code,
            driver_name=r.full_name,
            managed_by=UserRef(id=r.managed_by, name=r.manager),
            overdue_paise=int(r.overdue),
            outstanding_paise=int(r.outstanding),
            awaiting_approval_paise=int(r.awaiting),
            oldest_overdue_date=r.oldest,
            days_overdue=(today - r.oldest).days,
        )
        for r in session.execute(query)
    ]


def totals_for(session: Session, *, now: datetime, driver_ids: Sequence[int] | None) -> Position:
    """Business-wide (driver_ids None) or for some drivers: outstanding and overdue."""
    figures = charge_figures(now)
    query = _position_query(figures)
    if driver_ids is not None:
        if not driver_ids:
            return Position(0, 0)
        query = query.where(figures.c.driver_id.in_(list(driver_ids)))
    outstanding, overdue = session.execute(query).one()
    return Position(int(outstanding), int(overdue))
