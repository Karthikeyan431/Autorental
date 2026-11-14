"""What is left to pay on each day, and the oldest-unpaid-first suggestion
(docs/rent-and-payments.md §1 formulas and §6).

* **Net charge** = charge + approved adjustments.
* **Counted** = allocations that are not reversed and belong to an approved payment or an
  approved advance transaction (rule 13). Net charge - counted = the day balance.
* **Claimed** = counted plus allocations still waiting (payments awaiting approval, pending
  advance adjustments). A new allocation must fit net charge - claimed, so two waiting payments
  can never promise the same rupee twice (§6 step 3).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.time import business_date
from app.modules.payments.models import AdvanceTransaction, Payment, PaymentAllocation
from app.modules.rent.models import ChargeAdjustment, RentCharge


@dataclass(frozen=True)
class DayFigures:
    charge_id: int
    agreement_id: int
    driver_id: int
    rent_date: date
    net_paise: int
    counted_paise: int
    claimed_paise: int

    @property
    def balance_paise(self) -> int:
        return self.net_paise - self.counted_paise

    @property
    def available_paise(self) -> int:
        return self.net_paise - self.claimed_paise


def day_figures(
    session: Session,
    *,
    charge_ids: Iterable[int] | None = None,
    driver_id: int | None = None,
    up_to: date | None = None,
    exclude_payment_id: int | None = None,
) -> dict[int, DayFigures]:
    """Figures per charge; allocations of `exclude_payment_id` are left out (it is being
    re-confirmed or re-checked)."""
    approved_adj = (
        select(
            ChargeAdjustment.rent_charge_id.label("charge_id"),
            func.sum(ChargeAdjustment.amount_paise).label("adjusted"),
        )
        .where(ChargeAdjustment.status == "approved")
        .group_by(ChargeAdjustment.rent_charge_id)
        .subquery("adj")
    )
    counts = or_(Payment.status == "approved", AdvanceTransaction.status == "approved")
    claims = or_(
        Payment.status.in_(("approved", "awaiting_approval")),
        AdvanceTransaction.status.in_(("approved", "pending")),
    )
    allocation_filter: list[Any] = [PaymentAllocation.reversed_at.is_(None)]
    if exclude_payment_id is not None:
        allocation_filter.append(
            or_(
                PaymentAllocation.payment_id.is_(None),
                PaymentAllocation.payment_id != exclude_payment_id,
            )
        )
    alloc = (
        select(
            PaymentAllocation.rent_charge_id.label("charge_id"),
            func.sum(case((counts, PaymentAllocation.amount_paise), else_=0)).label("counted"),
            func.sum(case((claims, PaymentAllocation.amount_paise), else_=0)).label("claimed"),
        )
        .outerjoin(Payment, Payment.id == PaymentAllocation.payment_id)
        .outerjoin(
            AdvanceTransaction, AdvanceTransaction.id == PaymentAllocation.advance_transaction_id
        )
        .where(and_(*allocation_filter))
        .group_by(PaymentAllocation.rent_charge_id)
        .subquery("alloc")
    )
    query = (
        select(
            RentCharge.id,
            RentCharge.agreement_id,
            RentCharge.driver_id,
            RentCharge.rent_date,
            (RentCharge.amount_paise + func.coalesce(approved_adj.c.adjusted, 0)).label("net"),
            func.coalesce(alloc.c.counted, 0).label("counted"),
            func.coalesce(alloc.c.claimed, 0).label("claimed"),
        )
        .outerjoin(approved_adj, approved_adj.c.charge_id == RentCharge.id)
        .outerjoin(alloc, alloc.c.charge_id == RentCharge.id)
        .order_by(RentCharge.rent_date, RentCharge.id)
    )
    if charge_ids is not None:
        query = query.where(RentCharge.id.in_(list(charge_ids)))
    if driver_id is not None:
        query = query.where(RentCharge.driver_id == driver_id)
    if up_to is not None:
        query = query.where(RentCharge.rent_date <= up_to)
    return {
        r.id: DayFigures(
            charge_id=r.id,
            agreement_id=r.agreement_id,
            driver_id=r.driver_id,
            rent_date=r.rent_date,
            net_paise=int(r.net),
            counted_paise=int(r.counted),
            claimed_paise=int(r.claimed),
        )
        for r in session.execute(query)
    }


def oldest_unpaid(
    session: Session,
    driver_id: int,
    amount: int,
    *,
    now: datetime,
    exclude_payment_id: int | None = None,
) -> list[tuple[DayFigures, int]]:
    """Rule 4: a **suggestion** only. The oldest days with something left to pay (net of every
    claim), filled in date order up to `amount`."""
    plan: list[tuple[DayFigures, int]] = []
    left = amount
    figures = day_figures(
        session,
        driver_id=driver_id,
        up_to=business_date(now),
        exclude_payment_id=exclude_payment_id,
    )
    for day in figures.values():
        if left <= 0:
            break
        take = min(day.available_paise, left)
        if take > 0:
            plan.append((day, take))
            left -= take
    return plan
