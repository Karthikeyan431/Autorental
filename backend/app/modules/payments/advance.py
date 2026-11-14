"""Advance (docs/rent-and-payments.md §7; rule 5; Q5, Q14).

* A **deposit** is a payment with purpose `advance_deposit`; it adds to the balance only when
  the owner approves the payment (rule 13).
* **Using** advance against rent: staff (`adjustments.request`, money viewers) propose the amount
  as days; the transaction and its allocations stay pending and change nothing until the owner
  (`advance.decide`) approves. The setting `advance_adjustments_enabled` switches proposals off.
* **Refunds** stay off (Q5): refused with REFUNDS_DISABLED while `refunds_enabled` is false.
* **The balance never goes below 0**: a proposal must fit the balance less every other pending
  use; approval re-checks under the driver row lock, and a deferred constraint trigger refuses
  any commit that would leave the approved balance below 0.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.access import not_found
from app.modules.drivers.models import Driver
from app.modules.drivers.service import get_driver
from app.modules.payments.access import require_permission
from app.modules.payments.allocation import (
    agreements_of,
    check_days,
    insert_allocations,
    lock_agreements,
    reverse_allocations,
)
from app.modules.payments.claims import day_figures
from app.modules.payments.models import AdvanceTransaction, PaymentAllocation
from app.modules.payments.schemas import AllocationItem
from app.modules.rent.access import require_money_view
from app.modules.settings.models import SettingsVersion
from app.modules.settings.service import get_current_settings

REASON_ADJUSTMENT_REJECTED = "advance adjustment rejected"


def lock_driver(session: Session, driver_id: int) -> Driver:
    return session.scalars(
        select(Driver)
        .where(Driver.id == driver_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def advance_balance(session: Session, driver_id: int) -> int:
    total = session.scalar(
        select(func.coalesce(func.sum(AdvanceTransaction.amount_paise), 0)).where(
            AdvanceTransaction.driver_id == driver_id, AdvanceTransaction.status == "approved"
        )
    )
    return int(total or 0)


def pending_use(session: Session, driver_id: int) -> int:
    """Pending adjustments and refunds (stored negative), as a positive amount."""
    total = session.scalar(
        select(func.coalesce(func.sum(AdvanceTransaction.amount_paise), 0)).where(
            AdvanceTransaction.driver_id == driver_id,
            AdvanceTransaction.status == "pending",
            AdvanceTransaction.amount_paise < 0,
        )
    )
    return -int(total or 0)


def available_advance(session: Session, driver_id: int) -> int:
    return advance_balance(session, driver_id) - pending_use(session, driver_id)


def _settings(session: Session, now: datetime) -> SettingsVersion | None:
    return get_current_settings(session, now)


def _adjustments_on(session: Session, now: datetime) -> None:
    current = _settings(session, now)
    if current is not None and not current.advance_adjustments_enabled:
        raise AppError("ADVANCE_ADJUSTMENTS_OFF", "The owner has switched advance adjustments off.")


def _refunds_on(session: Session, now: datetime) -> None:
    current = _settings(session, now)
    if current is None or not current.refunds_enabled:
        raise AppError("REFUNDS_DISABLED", "Advance refunds are switched off.")


def _insufficient(available: int) -> AppError:
    return AppError(
        "ADVANCE_INSUFFICIENT",
        "This is more than the advance left (pending uses count too).",
        details={"available_paise": max(available, 0)},
    )


def _driver_for(session: Session, user: CurrentUser, driver_id: int) -> Driver:
    driver = get_driver(session, driver_id)
    require_money_view(user, driver)
    return lock_driver(session, driver.id)


def _audit_request(
    session: Session, tx: AdvanceTransaction, user: CurrentUser, now: datetime, ip: str | None
) -> None:
    write_audit(
        session,
        action=f"advance.{tx.kind}_requested",
        entity_type="advance_transaction",
        entity_id=tx.id,
        actor_id=user.id,
        after={"driver_id": tx.driver_id, "kind": tx.kind, "amount_paise": tx.amount_paise},
        reason=tx.reason,
        ip=ip,
        occurred_at=now,
    )


def request_advance_adjustment(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    items: list[AllocationItem],
    reason: str,
    *,
    now: datetime,
    ip: str | None = None,
) -> AdvanceTransaction:
    require_permission(user, Permission.ADJUSTMENTS_REQUEST)
    driver = _driver_for(session, user, driver_id)
    _adjustments_on(session, now)
    total = sum(i.amount_paise for i in items)
    available = available_advance(session, driver.id)
    if total > available:
        raise _insufficient(available)
    lock_agreements(session, agreements_of(session, [i.rent_charge_id for i in items]))
    check_days(session, driver, items, now=now)
    tx = AdvanceTransaction(
        driver_id=driver.id,
        kind="adjustment",
        amount_paise=-total,
        status="pending",
        requested_by=user.id,
        reason=reason,
    )
    session.add(tx)
    session.flush()
    insert_allocations(session, items, user=user, now=now, advance_transaction_id=tx.id)
    _audit_request(session, tx, user, now, ip)
    return tx


def request_refund(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    amount_paise: int,
    reason: str,
    *,
    now: datetime,
    ip: str | None = None,
) -> AdvanceTransaction:
    require_permission(user, Permission.ADJUSTMENTS_REQUEST)
    driver = _driver_for(session, user, driver_id)
    _refunds_on(session, now)
    available = available_advance(session, driver.id)
    if amount_paise > available:
        raise _insufficient(available)
    tx = AdvanceTransaction(
        driver_id=driver.id,
        kind="refund",
        amount_paise=-amount_paise,
        status="pending",
        requested_by=user.id,
        reason=reason,
    )
    session.add(tx)
    session.flush()
    _audit_request(session, tx, user, now, ip)
    return tx


def decide_advance(
    session: Session,
    user: CurrentUser,
    transaction_id: int,
    decision: str,
    reason: str | None,
    *,
    now: datetime,
    ip: str | None = None,
) -> AdvanceTransaction:
    # Imported here: the pay request service imports this package's claims module.
    from app.modules.pay_requests.service import refresh_pay_request_status

    require_permission(user, Permission.ADVANCE_DECIDE)
    found = session.get(AdvanceTransaction, transaction_id)
    if found is None:
        raise not_found()
    lock_driver(session, found.driver_id)
    tx = session.scalars(
        select(AdvanceTransaction)
        .where(AdvanceTransaction.id == transaction_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if tx.status != "pending":
        raise AppError(
            "ADVANCE_ALREADY_DECIDED",
            "This has already been decided.",
            details={"status": tx.status},
        )
    rows = list(
        session.scalars(
            select(PaymentAllocation).where(PaymentAllocation.advance_transaction_id == tx.id)
        )
    )
    if decision == "approved":
        if tx.kind == "refund":
            _refunds_on(session, now)
        else:
            _adjustments_on(session, now)
        if advance_balance(session, tx.driver_id) < -tx.amount_paise:
            raise _insufficient(advance_balance(session, tx.driver_id))
        lock_agreements(session, agreements_of(session, [a.rent_charge_id for a in rows]))
        figures = day_figures(session, charge_ids=[a.rent_charge_id for a in rows])
        for row in rows:
            day = figures[row.rent_charge_id]
            # The day's balance already counts approved allocations; this one is still pending.
            if row.amount_paise > day.balance_paise:
                raise AppError(
                    "ADVANCE_NO_LONGER_FITS",
                    f"The day {day.rent_date:%d %b %Y} no longer has room for this adjustment.",
                    details={"rent_charge_id": day.charge_id},
                )
        tx.status = "approved"
        tx.approved_by = user.id
        tx.approved_at = now
    else:
        reverse_allocations(
            session, rows, reason=REASON_ADJUSTMENT_REJECTED, actor_id=user.id, now=now
        )
        tx.status = "rejected"
    session.flush()
    write_audit(
        session,
        action=f"advance.{tx.kind}_{tx.status}",
        entity_type="advance_transaction",
        entity_id=tx.id,
        actor_id=user.id,
        before={"status": "pending"},
        after={"status": tx.status, "driver_id": tx.driver_id, "amount_paise": tx.amount_paise},
        reason=reason,
        ip=ip,
        occurred_at=now,
    )
    if tx.status == "approved":
        refresh_pay_request_status(session, tx.driver_id, now=now, actor_id=user.id)
    return tx
