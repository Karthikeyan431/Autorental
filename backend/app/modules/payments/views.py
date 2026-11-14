"""Read models for advance and reversal requests (docs/api.md "Payments", "Advance")."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.drivers.models import Driver
from app.modules.drivers.service import user_refs
from app.modules.payments.advance import advance_balance, pending_use
from app.modules.payments.models import (
    AdvanceTransaction,
    Payment,
    PaymentAllocation,
    ReversalRequest,
)
from app.modules.payments.schemas import (
    AdvanceOut,
    AdvanceTransactionOut,
    PaymentDriver,
    ReversalRequestOut,
)
from app.modules.payments.service import allocations_out
from app.modules.settings.service import get_current_settings


def transactions_out(
    session: Session, rows: list[AdvanceTransaction]
) -> list[AdvanceTransactionOut]:
    if not rows:
        return []
    allocations: dict[int, list[PaymentAllocation]] = {r.id: [] for r in rows}
    for a in session.scalars(
        select(PaymentAllocation).where(
            PaymentAllocation.advance_transaction_id.in_(list(allocations))
        )
    ):
        allocations[a.advance_transaction_id or 0].append(a)
    refs = user_refs(session, [r.requested_by for r in rows] + [r.approved_by for r in rows])
    return [
        AdvanceTransactionOut(
            id=r.id,
            kind=r.kind,  # type: ignore[arg-type]
            amount_paise=r.amount_paise,
            status=r.status,  # type: ignore[arg-type]
            payment_id=r.payment_id,
            reason=r.reason,
            requested_by=refs.get(r.requested_by) if r.requested_by else None,
            approved_by=refs.get(r.approved_by) if r.approved_by else None,
            approved_at=r.approved_at,
            created_at=r.created_at,
            allocations=allocations_out(session, allocations[r.id]),
        )
        for r in rows
    ]


def advance_out(session: Session, driver_id: int) -> AdvanceOut:
    settings = get_current_settings(session)
    rows = list(
        session.scalars(
            select(AdvanceTransaction)
            .where(AdvanceTransaction.driver_id == driver_id)
            .order_by(AdvanceTransaction.created_at.desc(), AdvanceTransaction.id.desc())
        )
    )
    return AdvanceOut(
        driver_id=driver_id,
        balance_paise=advance_balance(session, driver_id),
        pending_use_paise=pending_use(session, driver_id),
        adjustments_enabled=settings.advance_adjustments_enabled if settings else True,
        refunds_enabled=settings.refunds_enabled if settings else False,
        transactions=transactions_out(session, rows),
    )


def pending_advance(session: Session) -> list[AdvanceTransactionOut]:
    rows = list(
        session.scalars(
            select(AdvanceTransaction)
            .where(AdvanceTransaction.status == "pending")
            .order_by(AdvanceTransaction.created_at, AdvanceTransaction.id)
        )
    )
    return transactions_out(session, rows)


def reversal_requests_out(
    session: Session, rows: list[ReversalRequest]
) -> list[ReversalRequestOut]:
    if not rows:
        return []
    payments = {
        p.id: p
        for p in session.scalars(
            select(Payment).where(Payment.id.in_({r.payment_id for r in rows if r.payment_id}))
        )
    }
    drivers = {
        d.id: d
        for d in session.scalars(
            select(Driver).where(Driver.id.in_({p.driver_id for p in payments.values()}))
        )
    }
    refs = user_refs(session, [r.requested_by for r in rows] + [r.decided_by for r in rows])
    out: list[ReversalRequestOut] = []
    for r in rows:
        payment = payments[r.payment_id or 0]
        driver = drivers[payment.driver_id]
        out.append(
            ReversalRequestOut(
                id=r.id,
                payment_id=r.payment_id,
                driver=PaymentDriver(id=driver.id, code=driver.code, full_name=driver.full_name),
                amount_paise=payment.amount_paise,
                receipt_no=payment.receipt_no,
                reason=r.reason,
                requested_by=refs[r.requested_by],
                requested_at=r.created_at,
                decision=r.decision,  # type: ignore[arg-type]
                decided_by=refs.get(r.decided_by) if r.decided_by else None,
                decided_at=r.decided_at,
                decision_reason=r.decision_reason,
            )
        )
    return out


def pending_reversals(session: Session) -> list[ReversalRequestOut]:
    rows = list(
        session.scalars(
            select(ReversalRequest)
            .where(ReversalRequest.decision.is_(None), ReversalRequest.payment_id.is_not(None))
            .order_by(ReversalRequest.created_at, ReversalRequest.id)
        )
    )
    return reversal_requests_out(session, rows)
