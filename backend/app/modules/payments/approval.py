"""Owner approval and rejection (docs/rent-and-payments.md §5; rule 13; N7; D57, C4).

**Approve** one or many. Each payment runs in its own transaction (C4): with one shared
transaction, the locks taken for the first payment would be held while the next one waits for
its payment row, which a concurrent Confirm may hold while it waits for the same agreement.
Per payment, in this order:

1. Lock the payment; it must still await approval.
2. Re-lock the agreement rows of its days in id order (D53).
3. Check each day still has room for it among the *approved* figures (another payment may have
   been approved for the day first, or a waiver approved).
4. Set `approved`, issue the receipt number from the locked counter row, write the audit entry.
   An advance deposit becomes an approved advance `deposit`. The pay request is re-checked.

A payment that no longer fits is refused with a reason; the rest are approved. A payment without
confirmed days can be approved: the money is then unallocated credit that staff apply later
(Q15; D57 decision 2).

**Reject** needs a reason. Its allocations are marked reversed ("payment rejected"), nothing is
deleted (rule 11), and its UPI reference and statement line are released by the partial unique
indexes.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.core.time import business_date
from app.modules.drivers.access import not_found
from app.modules.pay_requests.service import refresh_pay_request_status
from app.modules.payments.access import require_permission
from app.modules.payments.allocation import (
    agreements_of,
    lock_agreements,
    lock_payment,
    reverse_allocations,
)
from app.modules.payments.claims import day_figures
from app.modules.payments.models import AdvanceTransaction, Payment, PaymentAllocation
from app.modules.payments.receipts import next_receipt_no
from app.modules.payments.schemas import ApprovalResult

REASON_REJECTED = "payment rejected"


def _not_awaiting(payment: Payment) -> AppError:
    return AppError(
        "PAYMENT_NOT_AWAITING_APPROVAL",
        "This payment has already been decided.",
        details={"status": payment.status},
    )


def _approve_one(session: Session, user: CurrentUser, payment_id: int, now: datetime) -> str:
    if session.get(Payment, payment_id) is None:
        raise not_found()
    payment = lock_payment(session, payment_id)
    if payment.status != "awaiting_approval":
        raise _not_awaiting(payment)
    rows = list(
        session.scalars(
            select(PaymentAllocation).where(
                PaymentAllocation.payment_id == payment.id,
                PaymentAllocation.reversed_at.is_(None),
            )
        )
    )
    lock_agreements(session, agreements_of(session, [a.rent_charge_id for a in rows]))
    figures = day_figures(
        session, charge_ids=[a.rent_charge_id for a in rows], exclude_payment_id=payment.id
    )
    for row in rows:
        day = figures[row.rent_charge_id]
        if row.amount_paise > day.balance_paise:
            raise AppError(
                "PAYMENT_NO_LONGER_FITS",
                f"The day {day.rent_date:%d %b %Y} no longer has room for this payment "
                "(another payment or a waiver was approved first). Confirm its days again.",
                details={
                    "rent_charge_id": day.charge_id,
                    "rent_date": day.rent_date.isoformat(),
                    "balance_paise": max(day.balance_paise, 0),
                },
            )
    if sum(a.amount_paise for a in rows) > payment.amount_paise:  # pragma: no cover - defensive
        raise AppError("PAYMENT_NO_LONGER_FITS", "The days add up to more than the payment.")
    receipt_no = next_receipt_no(session, business_date(now))  # before any change: autoflush
    payment.status = "approved"
    payment.approved_by = user.id
    payment.approved_at = now
    payment.receipt_no = receipt_no
    session.flush()
    if payment.purpose == "advance_deposit":
        session.add(
            AdvanceTransaction(
                driver_id=payment.driver_id,
                agreement_id=payment.agreement_id,
                kind="deposit",
                amount_paise=payment.amount_paise,
                payment_id=payment.id,
                status="approved",
                requested_by=payment.recorded_by,
                approved_by=user.id,
                approved_at=now,
                reason="Advance deposit",
            )
        )
        session.flush()
    write_audit(
        session,
        action="payment.approved",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=user.id,
        before={"status": "awaiting_approval"},
        after={
            "status": "approved",
            "driver_id": payment.driver_id,
            "amount_paise": payment.amount_paise,
            "receipt_no": payment.receipt_no,
            "allocated_paise": sum(a.amount_paise for a in rows),
        },
        occurred_at=now,
    )
    refresh_pay_request_status(session, payment.driver_id, now=now, actor_id=user.id)
    return receipt_no


def approve_payments(
    session: Session,
    user: CurrentUser,
    ids: list[int],
    *,
    now: datetime,
    ip: str | None = None,
    commit_each: bool = True,
) -> list[ApprovalResult]:
    require_permission(user, Permission.PAYMENTS_APPROVE)
    results: list[ApprovalResult] = []
    for payment_id in sorted(set(ids)):
        try:
            with session.begin_nested():
                receipt_no = _approve_one(session, user, payment_id, now)
            results.append(
                ApprovalResult(payment_id=payment_id, outcome="approved", receipt_no=receipt_no)
            )
        except AppError as exc:
            results.append(
                ApprovalResult(
                    payment_id=payment_id, outcome="refused", code=exc.code, message=exc.message
                )
            )
        if commit_each:
            session.commit()  # C4: one transaction per payment
    return results


def reject_payment(
    session: Session,
    user: CurrentUser,
    payment_id: int,
    reason: str,
    *,
    now: datetime,
    ip: str | None = None,
) -> Payment:
    require_permission(user, Permission.PAYMENTS_APPROVE)
    if session.get(Payment, payment_id) is None:
        raise not_found()
    payment = lock_payment(session, payment_id)
    if payment.status != "awaiting_approval":
        raise _not_awaiting(payment)
    rows = list(
        session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id))
    )
    reverse_allocations(session, rows, reason=REASON_REJECTED, actor_id=user.id, now=now)
    payment.status = "rejected"
    payment.rejected_by = user.id
    payment.rejected_at = now
    payment.rejection_reason = reason
    session.flush()
    write_audit(
        session,
        action="payment.rejected",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=user.id,
        before={"status": "awaiting_approval"},
        after={"status": "rejected", "driver_id": payment.driver_id},
        reason=reason,
        ip=ip,
        occurred_at=now,
    )
    refresh_pay_request_status(session, payment.driver_id, now=now, actor_id=user.id)
    return payment
