"""The allocation transaction (docs/rent-and-payments.md §6; rule 4; Q15, Q16; D53; D57).

Only a person's explicit Confirm creates allocations; a pay request or a suggestion never does.
In one transaction:

1. Lock the payment row.
2. Lock the agreement rows of the chosen days (and of the payment's current days) in id order,
   so two staff members cannot deadlock (`rent_charges` is insert-only and cannot be locked;
   D53).
3. Check each day belongs to this driver (ALLOCATION_WRONG_DRIVER), has accrued (no future
   days, Q16: ALLOCATION_FUTURE_DAY), is listed once (ALLOCATION_DUPLICATE_DAY) and fits what is
   left on the day after every other claim, waiting ones included (ALLOCATION_EXCEEDS_DAY); and
   that the total fits the payment's unallocated amount (ALLOCATION_EXCEEDS_PAYMENT).
4. Write the allocations and the audit entry.

* **Confirm days** (`PUT`): a payment awaiting approval. The new set replaces the old one; the
  old allocations are marked reversed ("days re-confirmed"), never deleted (rule 11).
* **Apply credit** (`POST`): an approved payment's leftover amount, applied to days that have
  since accrued. Add-only, counts at once (D57 decision 2), audited, listed on the payment.

Who: the owner, the driver's current manager and `reports.all` (D57 decision 1).
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser
from app.core.time import business_date
from app.modules.drivers.models import Driver
from app.modules.payments.access import require_days_confirm, visible_payment
from app.modules.payments.claims import DayFigures, day_figures, oldest_unpaid
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.payments.schemas import AllocationItem, SuggestedDay
from app.modules.rent.adjustments import lock_agreement
from app.modules.rent.models import RentCharge

REASON_RECONFIRMED = "days re-confirmed"


def lock_payment(session: Session, payment_id: int) -> Payment:
    return session.scalars(
        select(Payment)
        .where(Payment.id == payment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def lock_agreements(session: Session, agreement_ids: Iterable[int]) -> None:
    for agreement_id in sorted(set(agreement_ids)):
        lock_agreement(session, agreement_id)


def agreements_of(session: Session, charge_ids: Iterable[int]) -> set[int]:
    ids = list(set(charge_ids))
    if not ids:
        return set()
    return set(
        session.scalars(select(RentCharge.agreement_id).where(RentCharge.id.in_(ids)).distinct())
    )


def _refuse(code: str, message: str, **details: Any) -> AppError:
    return AppError(code, message, details=details)


def check_days(
    session: Session,
    driver: Driver,
    items: list[AllocationItem],
    *,
    now: datetime,
    exclude_payment_id: int | None = None,
) -> dict[int, DayFigures]:
    """Step 3 for each day. The caller holds the locks."""
    ids = [i.rent_charge_id for i in items]
    if len(ids) != len(set(ids)):
        raise _refuse("ALLOCATION_DUPLICATE_DAY", "Each day can be listed once.")
    figures = day_figures(session, charge_ids=ids, exclude_payment_id=exclude_payment_id)
    today = business_date(now)
    for item in items:
        day = figures.get(item.rent_charge_id)
        if day is None or day.driver_id != driver.id:
            raise _refuse(
                "ALLOCATION_WRONG_DRIVER",
                "A chosen day is not one of this driver's rent days.",
                rent_charge_id=item.rent_charge_id,
            )
        if day.rent_date > today:
            raise _refuse(
                "ALLOCATION_FUTURE_DAY",
                "Rent cannot be paid ahead: the day has not started yet.",
                rent_charge_id=item.rent_charge_id,
            )
        if item.amount_paise > day.available_paise:
            raise _refuse(
                "ALLOCATION_EXCEEDS_DAY",
                "This is more than is left to pay on the day (payments awaiting approval "
                "count too).",
                rent_charge_id=item.rent_charge_id,
                rent_date=day.rent_date.isoformat(),
                available_paise=max(day.available_paise, 0),
            )
    return figures


def insert_allocations(
    session: Session,
    items: list[AllocationItem],
    *,
    user: CurrentUser,
    now: datetime,
    payment_id: int | None = None,
    advance_transaction_id: int | None = None,
) -> list[PaymentAllocation]:
    rows = [
        PaymentAllocation(
            payment_id=payment_id,
            advance_transaction_id=advance_transaction_id,
            rent_charge_id=item.rent_charge_id,
            amount_paise=item.amount_paise,
            confirmed_by=user.id,
            confirmed_at=now,
        )
        for item in items
    ]
    session.add_all(rows)
    session.flush()
    return rows


def reverse_allocations(
    session: Session,
    rows: Iterable[PaymentAllocation],
    *,
    reason: str,
    actor_id: int,
    now: datetime,
) -> None:
    for row in rows:
        if row.reversed_at is None:
            row.reversed_at = now
            row.reversed_by = actor_id
            row.reversal_reason = reason
    session.flush()


def _days_audit(figures: dict[int, DayFigures], items: list[AllocationItem]) -> list[Any]:
    return [
        {
            "rent_charge_id": i.rent_charge_id,
            "rent_date": figures[i.rent_charge_id].rent_date,
            "amount_paise": i.amount_paise,
        }
        for i in items
    ]


def _active(session: Session, payment_id: int) -> list[PaymentAllocation]:
    return list(
        session.scalars(
            select(PaymentAllocation).where(
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.reversed_at.is_(None),
            )
        )
    )


def _prepare(session: Session, user: CurrentUser, payment_id: int) -> tuple[Payment, Driver]:
    payment, driver = visible_payment(session, user, payment_id)
    require_days_confirm(user, driver)
    if payment.purpose != "rent":
        raise _refuse(
            "DEPOSIT_NOT_ALLOCATED",
            "An advance deposit is not paid towards days; use an advance adjustment.",
        )
    return lock_payment(session, payment.id), driver


def suggest_days(session: Session, payment: Payment, *, now: datetime) -> list[SuggestedDay]:
    """Oldest unpaid days first, for the payment's unallocated amount. A suggestion only."""
    if payment.status == "approved":
        left = payment.amount_paise - sum(a.amount_paise for a in _active(session, payment.id))
        exclude = None
    else:
        left = payment.amount_paise
        exclude = payment.id  # confirming again replaces this payment's days
    plan = oldest_unpaid(session, payment.driver_id, left, now=now, exclude_payment_id=exclude)
    return [
        SuggestedDay(
            rent_charge_id=day.charge_id,
            rent_date=day.rent_date,
            available_paise=day.available_paise,
            amount_paise=amount,
        )
        for day, amount in plan
    ]


def confirm_days(
    session: Session,
    user: CurrentUser,
    payment_id: int,
    items: list[AllocationItem],
    *,
    now: datetime,
    ip: str | None = None,
) -> list[PaymentAllocation]:
    payment, driver = _prepare(session, user, payment_id)
    if payment.status != "awaiting_approval":
        raise _refuse(
            "PAYMENT_NOT_AWAITING_APPROVAL",
            "The days of a decided payment cannot be changed.",
            status=payment.status,
        )
    current = _active(session, payment.id)
    lock_agreements(
        session,
        agreements_of(session, [i.rent_charge_id for i in items])
        | agreements_of(session, [a.rent_charge_id for a in current]),
    )
    figures = check_days(session, driver, items, now=now, exclude_payment_id=payment.id)
    total = sum(i.amount_paise for i in items)
    if total > payment.amount_paise:
        raise _refuse(
            "ALLOCATION_EXCEEDS_PAYMENT",
            "The days add up to more than the payment.",
            unallocated_paise=payment.amount_paise,
        )
    reverse_allocations(session, current, reason=REASON_RECONFIRMED, actor_id=user.id, now=now)
    rows = insert_allocations(session, items, user=user, now=now, payment_id=payment.id)
    write_audit(
        session,
        action="payment.days_confirmed",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=user.id,
        before={"allocation_ids": [a.id for a in current]} if current else None,
        after={"driver_id": driver.id, "days": _days_audit(figures, items)},
        ip=ip,
        occurred_at=now,
    )
    return rows


def apply_credit(
    session: Session,
    user: CurrentUser,
    payment_id: int,
    items: list[AllocationItem],
    *,
    now: datetime,
    ip: str | None = None,
) -> list[PaymentAllocation]:
    # Imported here: the pay request service imports this package's claims module.
    from app.modules.pay_requests.service import refresh_pay_request_status

    payment, driver = _prepare(session, user, payment_id)
    if payment.status != "approved":
        raise _refuse(
            "PAYMENT_NOT_APPROVED",
            "Credit can be applied only from an approved payment; confirm the days instead.",
            status=payment.status,
        )
    if not items:
        raise _refuse("ALLOCATION_EMPTY", "Choose at least one day.")
    lock_agreements(session, agreements_of(session, [i.rent_charge_id for i in items]))
    figures = check_days(session, driver, items, now=now)
    left = payment.amount_paise - sum(a.amount_paise for a in _active(session, payment.id))
    if sum(i.amount_paise for i in items) > left:
        raise _refuse(
            "ALLOCATION_EXCEEDS_PAYMENT",
            "The days add up to more than the credit left on this payment.",
            unallocated_paise=left,
        )
    rows = insert_allocations(session, items, user=user, now=now, payment_id=payment.id)
    write_audit(
        session,
        action="payment.credit_applied",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=user.id,
        after={"driver_id": driver.id, "days": _days_audit(figures, items)},
        ip=ip,
        occurred_at=now,
    )
    refresh_pay_request_status(session, driver.id, now=now, actor_id=user.id)
    return rows
