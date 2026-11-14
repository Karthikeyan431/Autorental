"""Payment reversals (docs/rent-and-payments.md §7; Q4; rule 11).

Nothing financial is edited or deleted. Staff (`adjustments.request`) ask for an approved
payment to be reversed, with a reason; one request may wait per payment. The owner
(`payments.reverse_decide`) decides. On approval: the payment becomes `reversed`, its allocations
are marked reversed ("payment reversed"), which restores the days' balances, its receipt is
marked cancelled (the number is kept, so the sequence has no gaps), and its UPI reference is
released. An advance deposit can be reversed only while the advance it added is still unused
(ADVANCE_IN_USE; rule 5).
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.access import not_found
from app.modules.drivers.service import get_driver
from app.modules.pay_requests.service import refresh_pay_request_status
from app.modules.payments.access import require_permission, visible_payment
from app.modules.payments.advance import available_advance, lock_driver
from app.modules.payments.allocation import lock_payment, reverse_allocations
from app.modules.payments.models import AdvanceTransaction, PaymentAllocation, ReversalRequest

REASON_REVERSED = "payment reversed"


def _already_requested() -> AppError:
    return AppError("REVERSAL_ALREADY_REQUESTED", "A reversal of this payment is already waiting.")


def request_reversal(
    session: Session,
    user: CurrentUser,
    payment_id: int,
    reason: str,
    *,
    now: datetime,
    ip: str | None = None,
) -> ReversalRequest:
    require_permission(user, Permission.ADJUSTMENTS_REQUEST)
    payment, _ = visible_payment(session, user, payment_id)
    payment = lock_payment(session, payment.id)
    if payment.status != "approved":
        raise AppError(
            "PAYMENT_NOT_APPROVED",
            "Only an approved payment can be reversed. The owner rejects a waiting one.",
            details={"status": payment.status},
        )
    waiting = session.scalar(
        select(func.count())
        .select_from(ReversalRequest)
        .where(ReversalRequest.payment_id == payment.id, ReversalRequest.decision.is_(None))
    )
    if waiting:
        raise _already_requested()
    request = ReversalRequest(payment_id=payment.id, reason=reason, requested_by=user.id)
    try:
        with session.begin_nested():
            session.add(request)
            session.flush()
    except IntegrityError as exc:
        raise _already_requested() from exc
    write_audit(
        session,
        action="reversal_request.created",
        entity_type="reversal_request",
        entity_id=request.id,
        actor_id=user.id,
        after={"payment_id": payment.id, "driver_id": payment.driver_id},
        reason=reason,
        ip=ip,
        occurred_at=now,
    )
    return request


def decide_reversal(
    session: Session,
    user: CurrentUser,
    request_id: int,
    decision: str,
    reason: str | None,
    *,
    now: datetime,
    ip: str | None = None,
) -> ReversalRequest:
    require_permission(user, Permission.PAYMENTS_REVERSE_DECIDE)
    found = session.get(ReversalRequest, request_id)
    if found is None or found.payment_id is None:
        raise not_found()
    payment = lock_payment(session, found.payment_id)
    request = session.scalars(
        select(ReversalRequest)
        .where(ReversalRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if request.decision is not None:
        raise AppError(
            "REVERSAL_ALREADY_DECIDED",
            "This reversal has already been decided.",
            details={"decision": request.decision},
        )
    if decision == "approved":
        if payment.status != "approved":
            raise AppError(
                "PAYMENT_NOT_APPROVED",
                "Only an approved payment can be reversed.",
                details={"status": payment.status},
            )
        if payment.purpose == "advance_deposit":
            driver = lock_driver(session, get_driver(session, payment.driver_id).id)
            if available_advance(session, driver.id) < payment.amount_paise:
                raise AppError(
                    "ADVANCE_IN_USE",
                    "Part of this deposit has already been used or is waiting to be used.",
                )
            session.add(
                AdvanceTransaction(
                    driver_id=payment.driver_id,
                    agreement_id=payment.agreement_id,
                    kind="reversal",
                    amount_paise=-payment.amount_paise,
                    payment_id=payment.id,
                    status="approved",
                    requested_by=request.requested_by,
                    approved_by=user.id,
                    approved_at=now,
                    reason=request.reason,
                )
            )
        rows = session.scalars(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        )
        reverse_allocations(session, rows, reason=REASON_REVERSED, actor_id=user.id, now=now)
        payment.status = "reversed"
        payment.reversed_by = user.id
        payment.reversed_at = now
        payment.receipt_cancelled_at = now
    request.decision = decision
    request.decided_by = user.id
    request.decided_at = now
    request.decision_reason = reason
    session.flush()
    write_audit(
        session,
        action=f"reversal_request.{decision}",
        entity_type="reversal_request",
        entity_id=request.id,
        actor_id=user.id,
        before={"decision": None},
        after={"decision": decision, "payment_id": payment.id},
        reason=reason,
        ip=ip,
        occurred_at=now,
    )
    if decision == "approved":
        write_audit(
            session,
            action="payment.reversed",
            entity_type="payment",
            entity_id=payment.id,
            actor_id=user.id,
            before={"status": "approved"},
            after={
                "status": "reversed",
                "driver_id": payment.driver_id,
                "receipt_no": payment.receipt_no,
                "receipt_cancelled": True,
            },
            reason=request.reason,
            ip=ip,
            occurred_at=now,
        )
        refresh_pay_request_status(session, payment.driver_id, now=now, actor_id=user.id)
    return request
