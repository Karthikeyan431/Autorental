"""Recording payments, reading them, and the receipt (docs/rent-and-payments.md §3 and §5).

* **Record** (`payments.record`, any driver; D57 decision 1): amount, method (UPI or cash, N6),
  purpose (rent or advance deposit), the UPI reference or UTR (required for UPI; a duplicate is
  refused while the earlier payment still stands), the received date (not in the future) and a
  proof photo (required for staff-recorded payments; D57 decision 3). Every payment starts
  `awaiting_approval` and creates **no** allocation (rule 4). The driver's open pay request is
  linked. A repeated `idempotency_key` returns the same payment (a double tap creates one).
* Visibility: see `app.modules.payments.access`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import Page, PageParams
from app.core.permissions import CurrentUser, Permission
from app.core.time import business_date
from app.modules.agreements.models import Agreement
from app.modules.documents.service import store_document
from app.modules.drivers.models import Driver
from app.modules.drivers.service import get_driver, user_refs
from app.modules.pay_requests.models import PayRequest
from app.modules.pay_requests.service import open_request
from app.modules.payments.access import (
    can_view_payment,
    payment_scope,
    require_permission,
    visible_payment,
)
from app.modules.payments.models import (
    AdvanceTransaction,
    Payment,
    PaymentAllocation,
    ReversalRequest,
)
from app.modules.payments.receipts import ReceiptDay, ReceiptSheet, render_receipt_pdf
from app.modules.payments.schemas import (
    AllocationOut,
    PaymentCreate,
    PaymentDriver,
    PaymentOut,
    PaymentsSummary,
)
from app.modules.rent.access import can_view_money, money_scope
from app.modules.rent.models import RentCharge
from app.modules.settings.service import get_current_settings

PROOF_MAX_SIDE = 1600
_SOURCES = {"cash": "cash_office", "upi": "upi_direct"}


def _same_request(payment: Payment, data: PaymentCreate, user: CurrentUser) -> bool:
    return (
        payment.recorded_by == user.id
        and payment.driver_id == data.driver_id
        and payment.amount_paise == data.amount_paise
        and payment.method == data.method
        and payment.purpose == data.purpose
        and payment.reference == data.reference
        and payment.received_on == data.received_on
    )


def _by_key(session: Session, key: str) -> Payment | None:
    return session.scalars(select(Payment).where(Payment.idempotency_key == key)).one_or_none()


def _replay(payment: Payment, data: PaymentCreate, user: CurrentUser) -> Payment:
    if not _same_request(payment, data, user):
        raise AppError(
            "IDEMPOTENCY_KEY_REUSED",
            "This form was already used for a different payment. Reload and try again.",
        )
    return payment


def _duplicate_reference() -> AppError:
    return AppError(
        "DUPLICATE_REFERENCE",
        "A payment with this UPI reference is already recorded.",
    )


def _agreement_for(session: Session, driver_id: int, purpose: str) -> Agreement:
    """Rent: the active agreement, else the latest ended one (arrears). Advance deposit: an
    active or draft agreement (Q14: the deposit is set per agreement)."""
    statuses = ("active", "ended") if purpose == "rent" else ("active", "draft")
    agreement = session.scalars(
        select(Agreement)
        .where(Agreement.driver_id == driver_id, Agreement.status.in_(statuses))
        .order_by(case((Agreement.status == "active", 0), else_=1), Agreement.start_date.desc())
        .limit(1)
    ).one_or_none()
    if agreement is None:
        raise AppError(
            "NO_AGREEMENT",
            "This driver has no agreement to take a payment for.",
        )
    return agreement


def record_payment(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    data: PaymentCreate,
    *,
    proof: bytes | None,
    now: datetime,
    ip: str | None = None,
) -> Payment:
    require_permission(user, Permission.PAYMENTS_RECORD)
    existing = _by_key(session, data.idempotency_key)
    if existing is not None:
        return _replay(existing, data, user)
    driver = get_driver(session, data.driver_id)
    if data.received_on > business_date(now):
        raise AppError("RECEIVED_DATE_IN_FUTURE", "The received date cannot be in the future.")
    if data.method == "upi" and data.reference is None:
        raise AppError(
            "REFERENCE_REQUIRED", "Enter the UPI reference or UTR from the payment screenshot."
        )
    if proof is None:
        raise AppError(
            "PROOF_REQUIRED", "Add a photo of the UPI screenshot or the cash slip.", status_code=422
        )
    agreement = _agreement_for(session, driver.id, data.purpose)
    if data.reference is not None:
        taken = session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.method == data.method,
                Payment.reference == data.reference,
                Payment.status.not_in(("rejected", "reversed")),
            )
        )
        if taken:
            raise _duplicate_reference()
    request = open_request(session, driver.id) if data.purpose == "rent" else None
    payment = Payment(
        driver_id=driver.id,
        agreement_id=agreement.id,
        amount_paise=data.amount_paise,
        method=data.method,
        source=_SOURCES[data.method],
        purpose=data.purpose,
        reference=data.reference,
        received_on=data.received_on,
        pay_request_id=request.id if request is not None else None,
        recorded_by=user.id,
        idempotency_key=data.idempotency_key,
    )
    try:
        with session.begin_nested():
            session.add(payment)
            session.flush()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_payments_idempotency_key":
            again = _by_key(session, data.idempotency_key)
            if again is not None:
                return _replay(again, data, user)
        if constraint == "unique_payment_reference":
            raise _duplicate_reference() from exc
        raise
    document = store_document(
        session,
        settings,
        data=proof,
        owner_type="payment",
        owner_id=payment.id,
        doc_type="payment_proof",
        uploaded_by=user.id,
        max_side=PROOF_MAX_SIDE,
    )
    payment.proof_document_id = document.id
    session.flush()
    write_audit(
        session,
        action="payment.recorded",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=user.id,
        after={
            "driver_id": driver.id,
            "agreement_id": agreement.id,
            "amount_paise": payment.amount_paise,
            "method": payment.method,
            "purpose": payment.purpose,
            "received_on": payment.received_on,
            "pay_request_id": payment.pay_request_id,
            "has_reference": payment.reference is not None,
        },
        ip=ip,
        occurred_at=now,
    )
    return payment


def active_allocations(session: Session, payment_id: int) -> list[PaymentAllocation]:
    return list(
        session.scalars(
            select(PaymentAllocation)
            .where(
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.reversed_at.is_(None),
            )
            .order_by(PaymentAllocation.id)
        )
    )


def allocations_out(session: Session, rows: list[PaymentAllocation]) -> list[AllocationOut]:
    if not rows:
        return []
    dates = dict(
        session.execute(
            select(RentCharge.id, RentCharge.rent_date).where(
                RentCharge.id.in_({r.rent_charge_id for r in rows})
            )
        )
        .tuples()
        .all()
    )
    refs = user_refs(session, [r.confirmed_by for r in rows])
    return [
        AllocationOut(
            id=r.id,
            rent_charge_id=r.rent_charge_id,
            rent_date=dates[r.rent_charge_id],
            amount_paise=r.amount_paise,
            confirmed_by=refs[r.confirmed_by],
            confirmed_at=r.confirmed_at,
            reversed_at=r.reversed_at,
            reversal_reason=r.reversal_reason,
        )
        for r in sorted(rows, key=lambda a: (dates[a.rent_charge_id], a.id))
    ]


def payments_out(session: Session, user: CurrentUser, payments: list[Payment]) -> list[PaymentOut]:
    if not payments:
        return []
    ids = [p.id for p in payments]
    drivers = {
        d.id: d
        for d in session.scalars(
            select(Driver).where(Driver.id.in_({p.driver_id for p in payments}))
        )
    }
    allocations: dict[int, list[PaymentAllocation]] = {pid: [] for pid in ids}
    for row in session.scalars(
        select(PaymentAllocation).where(PaymentAllocation.payment_id.in_(ids))
    ):
        allocations[row.payment_id or 0].append(row)
    pending = dict(
        session.execute(
            select(ReversalRequest.payment_id, ReversalRequest.id).where(
                ReversalRequest.payment_id.in_(ids), ReversalRequest.decision.is_(None)
            )
        )
        .tuples()
        .all()
    )
    refs = user_refs(
        session,
        [p.recorded_by for p in payments]
        + [p.approved_by for p in payments]
        + [p.rejected_by for p in payments],
    )
    out: list[PaymentOut] = []
    for p in payments:
        driver = drivers[p.driver_id]
        rows = allocations[p.id]
        allocated = sum(a.amount_paise for a in rows if a.reversed_at is None)
        money = can_view_money(user, driver)
        out.append(
            PaymentOut(
                id=p.id,
                driver=PaymentDriver(id=driver.id, code=driver.code, full_name=driver.full_name),
                agreement_id=p.agreement_id,
                amount_paise=p.amount_paise,
                method=p.method,  # type: ignore[arg-type]
                source=p.source,
                purpose=p.purpose,  # type: ignore[arg-type]
                reference=p.reference,
                received_on=p.received_on,
                status=p.status,  # type: ignore[arg-type]
                recorded_by=refs[p.recorded_by],
                recorded_at=p.created_at,
                approved_by=refs.get(p.approved_by) if p.approved_by else None,
                approved_at=p.approved_at,
                rejected_by=refs.get(p.rejected_by) if p.rejected_by else None,
                rejected_at=p.rejected_at,
                rejection_reason=p.rejection_reason,
                reversed_at=p.reversed_at,
                receipt_no=p.receipt_no,
                receipt_cancelled=p.receipt_cancelled_at is not None,
                pay_request_id=p.pay_request_id,
                proof_document_id=p.proof_document_id,
                allocated_paise=allocated,
                unallocated_paise=p.amount_paise - allocated
                if p.status in ("awaiting_approval", "approved")
                else 0,
                days_confirmed=allocated > 0 or p.purpose == "advance_deposit",
                # The recorder sees the payment but only money viewers see its days (D57).
                allocations=allocations_out(session, rows) if money else [],
                pending_reversal_id=pending.get(p.id),
                can_confirm_days=money
                and user.has(Permission.PAYMENTS_RECORD)
                and p.purpose == "rent"
                and p.status in ("awaiting_approval", "approved"),
            )
        )
    return out


def payment_out(session: Session, user: CurrentUser, payment: Payment) -> PaymentOut:
    return payments_out(session, user, [payment])[0]


def get_payment(session: Session, user: CurrentUser, payment_id: int) -> Payment:
    payment, _ = visible_payment(session, user, payment_id)
    return payment


def list_payments(
    session: Session,
    user: CurrentUser,
    params: PageParams,
    *,
    status: str | None = None,
    driver_id: int | None = None,
    recorded_by: int | None = None,
    method: str | None = None,
) -> Page[PaymentOut]:
    query = select(Payment)
    scope = payment_scope(user)
    if scope is not None:
        query = query.where(scope)
    if status is not None:
        query = query.where(Payment.status == status)
    if driver_id is not None:
        query = query.where(Payment.driver_id == driver_id)
    if recorded_by is not None:
        query = query.where(Payment.recorded_by == recorded_by)
    if method is not None:
        query = query.where(Payment.method == method)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if status == "awaiting_approval":
        # The approval queue: statement-matched first (Week 7), then the oldest.
        order: list[Any] = [Payment.statement_line_id.is_(None), Payment.created_at, Payment.id]
    else:
        order = [Payment.created_at.desc(), Payment.id.desc()]
    rows = list(
        session.scalars(query.order_by(*order).limit(params.page_size).offset(params.offset))
    )
    return Page[PaymentOut](
        items=payments_out(session, user, rows),
        total=int(total),
        page=params.page,
        page_size=params.page_size,
    )


def receipt_pdf(session: Session, user: CurrentUser, payment_id: int) -> tuple[Payment, bytes]:
    payment, driver = visible_payment(session, user, payment_id)
    if payment.receipt_no is None or payment.approved_at is None:
        raise AppError("RECEIPT_NOT_ISSUED", "A receipt is issued when the owner approves.")
    settings = get_current_settings(session)
    rows = [
        a
        for a in session.scalars(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)
        )
        if a.reversed_at is None or payment.status == "reversed"
    ]
    if payment.status == "reversed":
        rows = [a for a in rows if a.reversal_reason == "payment reversed"]
    dates = dict(
        session.execute(
            select(RentCharge.id, RentCharge.rent_date).where(
                RentCharge.id.in_({a.rent_charge_id for a in rows})
            )
        )
        .tuples()
        .all()
    )
    days = sorted(
        (ReceiptDay(dates[a.rent_charge_id], a.amount_paise) for a in rows),
        key=lambda d: d.rent_date,
    )
    covered = sum(d.amount_paise for d in days)
    sheet = ReceiptSheet(
        business_name=(settings.business_name if settings else None) or "Auto rentals",
        business_address=settings.business_address if settings else None,
        receipt_no=payment.receipt_no,
        approved_on=business_date(payment.approved_at),
        driver_name=driver.full_name,
        driver_code=driver.code,
        amount_paise=payment.amount_paise,
        method=payment.method,
        reference=payment.reference,
        received_on=payment.received_on,
        purpose=payment.purpose,
        days=days,
        unallocated_paise=0
        if payment.purpose == "advance_deposit"
        else payment.amount_paise - covered,
        cancelled=payment.receipt_cancelled_at is not None,
    )
    return payment, render_receipt_pdf(sheet)


def summary(session: Session, user: CurrentUser, *, now: datetime) -> PaymentsSummary:
    """Dashboard figures, scoped like D54: business-wide for the owner and `reports.all`."""
    scope = money_scope(session, user)
    waiting = select(
        func.count(),
        func.coalesce(func.sum(Payment.amount_paise), 0),
    ).where(Payment.status == "awaiting_approval")
    unconfirmed = (
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.status == "awaiting_approval",
            Payment.purpose == "rent",
            ~select(PaymentAllocation.id)
            .where(
                PaymentAllocation.payment_id == Payment.id,
                PaymentAllocation.reversed_at.is_(None),
            )
            .exists(),
        )
    )
    today = business_date(now)
    requests = select(
        func.count(),
        func.count().filter(PayRequest.send_count > 0),
        func.count().filter(PayRequest.status == "paid"),
        func.count().filter(PayRequest.status == "open"),
    ).where(PayRequest.period_end == today, PayRequest.status != "superseded")
    reversals = (
        select(func.count())
        .select_from(ReversalRequest)
        .join(Payment, Payment.id == ReversalRequest.payment_id)
        .where(ReversalRequest.decision.is_(None))
    )
    advance = (
        select(func.count())
        .select_from(AdvanceTransaction)
        .where(AdvanceTransaction.status == "pending")
    )
    if scope is not None:
        waiting = waiting.where(Payment.driver_id.in_(scope))
        unconfirmed = unconfirmed.where(Payment.driver_id.in_(scope))
        requests = requests.where(PayRequest.driver_id.in_(scope))
        reversals = reversals.where(Payment.driver_id.in_(scope))
        advance = advance.where(AdvanceTransaction.driver_id.in_(scope))
    count, amount = session.execute(waiting).one()
    total, sent, paid, unpaid = session.execute(requests).one()
    return PaymentsSummary(
        awaiting_count=int(count),
        awaiting_paise=int(amount),
        awaiting_days_unconfirmed=int(session.scalar(unconfirmed) or 0),
        pending_reversals=int(session.scalar(reversals) or 0),
        pending_advance=int(session.scalar(advance) or 0),
        requests_today=int(total),
        sent_today=int(sent),
        paid_today=int(paid),
        unpaid_today=int(unpaid),
    )


__all__ = ["can_view_payment"]
