"""Payment, reversal and advance endpoints (docs/api.md "Payments", "Advance").

* Record: `payments.record`, any driver (D57 decision 1). The recorder sees what they recorded.
* Confirm days, apply credit, the suggestion: `payments.record` plus the money rule (owner,
  current manager, `reports.all`); a recorder who is not one of them gets 403.
* Approve and reject: `payments.approve` (owner). Reversal decisions: `payments.reverse_decide`
  (owner). Advance decisions: `advance.decide` (owner).
* Reversal requests and advance proposals: `adjustments.request`.

Static paths are declared before `/payments/{payment_id}`.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.db import get_session
from app.core.errors import AppError
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.drivers.router import read_upload
from app.modules.drivers.service import get_driver
from app.modules.payments import advance, allocation, approval, reversals, service, views
from app.modules.payments.access import require_days_confirm, visible_payment
from app.modules.payments.models import AdvanceTransaction
from app.modules.payments.schemas import (
    AdvanceAdjustmentIn,
    AdvanceDecisionIn,
    AdvanceOut,
    AdvanceRefundIn,
    AdvanceTransactionOut,
    AllocationsIn,
    ApprovalResult,
    ApproveIn,
    PaymentCreate,
    PaymentOut,
    PaymentsSummary,
    PaymentStatus,
    RejectIn,
    ReversalDecisionIn,
    ReversalRequestIn,
    ReversalRequestOut,
    SuggestionOut,
)
from app.modules.rent.access import require_money_view

router = APIRouter(tags=["payments"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Recorder = Annotated[CurrentUser, Depends(require(Permission.PAYMENTS_RECORD))]
Approver = Annotated[CurrentUser, Depends(require(Permission.PAYMENTS_APPROVE))]
ReversalDecider = Annotated[CurrentUser, Depends(require(Permission.PAYMENTS_REVERSE_DECIDE))]
Requester = Annotated[CurrentUser, Depends(require(Permission.ADJUSTMENTS_REQUEST))]
AdvanceDecider = Annotated[CurrentUser, Depends(require(Permission.ADVANCE_DECIDE))]


@router.get("/payments", response_model=Page[PaymentOut])
def list_payments(
    session: DbSession,
    user: SignedIn,
    params: Annotated[PageParams, Depends(page_params)],
    payment_status: Annotated[PaymentStatus | None, Query(alias="status")] = None,
    driver_id: int | None = None,
    recorded_by: int | None = None,
    method: Literal["upi", "cash"] | None = None,
) -> Page[PaymentOut]:
    return service.list_payments(
        session,
        user,
        params,
        status=payment_status,
        driver_id=driver_id,
        recorded_by=recorded_by,
        method=method,
    )


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(
    request: Request,
    session: DbSession,
    user: Recorder,
    driver_id: Annotated[int, Form()],
    amount_paise: Annotated[int, Form()],
    method: Annotated[str, Form()],
    received_on: Annotated[date, Form()],
    idempotency_key: Annotated[str, Form()],
    purpose: Annotated[str, Form()] = "rent",
    reference: Annotated[str | None, Form()] = None,
    proof: Annotated[UploadFile | None, File()] = None,
) -> PaymentOut:
    try:
        data = PaymentCreate.model_validate(
            {
                "driver_id": driver_id,
                "amount_paise": amount_paise,
                "method": method,
                "purpose": purpose,
                "reference": reference or None,
                "received_on": received_on,
                "idempotency_key": idempotency_key,
            }
        )
    except ValidationError as exc:
        raise AppError(
            "VALIDATION_ERROR",
            "Some fields are not valid.",
            status_code=422,
            details={"fields": sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})},
        ) from exc
    payment = service.record_payment(
        session,
        request.app.state.settings,
        user,
        data,
        proof=read_upload(proof) if proof is not None else None,
        now=clock.utc_now(),
        ip=client_ip(request),
    )
    return service.payment_out(session, user, payment)


@router.get("/payments/summary", response_model=PaymentsSummary)
def payments_summary(session: DbSession, user: SignedIn) -> PaymentsSummary:
    return service.summary(session, user, now=clock.utc_now())


@router.post("/payments/approve", response_model=list[ApprovalResult])
def approve(
    body: ApproveIn, request: Request, session: DbSession, user: Approver
) -> list[ApprovalResult]:
    return approval.approve_payments(
        session, user, body.ids, now=clock.utc_now(), ip=client_ip(request)
    )


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, session: DbSession, user: SignedIn) -> PaymentOut:
    return service.payment_out(session, user, service.get_payment(session, user, payment_id))


@router.get("/payments/{payment_id}/suggestion", response_model=SuggestionOut)
def suggestion(payment_id: int, session: DbSession, user: Recorder) -> SuggestionOut:
    payment, driver = visible_payment(session, user, payment_id)
    require_days_confirm(user, driver)
    days = allocation.suggest_days(session, payment, now=clock.utc_now())
    out = service.payment_out(session, user, payment)
    left = payment.amount_paise if payment.status == "awaiting_approval" else out.unallocated_paise
    return SuggestionOut(unallocated_paise=left, items=days)


@router.put("/payments/{payment_id}/allocations", response_model=PaymentOut)
def confirm_days(
    payment_id: int, body: AllocationsIn, request: Request, session: DbSession, user: Recorder
) -> PaymentOut:
    allocation.confirm_days(
        session, user, payment_id, body.items, now=clock.utc_now(), ip=client_ip(request)
    )
    return service.payment_out(session, user, service.get_payment(session, user, payment_id))


@router.post("/payments/{payment_id}/allocations", response_model=PaymentOut)
def apply_credit(
    payment_id: int, body: AllocationsIn, request: Request, session: DbSession, user: Recorder
) -> PaymentOut:
    allocation.apply_credit(
        session, user, payment_id, body.items, now=clock.utc_now(), ip=client_ip(request)
    )
    return service.payment_out(session, user, service.get_payment(session, user, payment_id))


@router.post("/payments/{payment_id}/reject", response_model=PaymentOut)
def reject(
    payment_id: int, body: RejectIn, request: Request, session: DbSession, user: Approver
) -> PaymentOut:
    payment = approval.reject_payment(
        session, user, payment_id, body.reason, now=clock.utc_now(), ip=client_ip(request)
    )
    return service.payment_out(session, user, payment)


@router.get(
    "/payments/{payment_id}/receipt.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def receipt(payment_id: int, session: DbSession, user: SignedIn) -> Response:
    payment, pdf = service.receipt_pdf(session, user, payment_id)
    name = (payment.receipt_no or "receipt").replace("/", "-")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # D40: PDFs are always downloaded, never shown inline.
            "Content-Disposition": f'attachment; filename="{name}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/payments/{payment_id}/reversal-requests",
    response_model=ReversalRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def request_reversal(
    payment_id: int,
    body: ReversalRequestIn,
    request: Request,
    session: DbSession,
    user: Requester,
) -> ReversalRequestOut:
    found = reversals.request_reversal(
        session, user, payment_id, body.reason, now=clock.utc_now(), ip=client_ip(request)
    )
    return views.reversal_requests_out(session, [found])[0]


@router.get("/reversal-requests", response_model=list[ReversalRequestOut])
def list_reversal_requests(session: DbSession, user: ReversalDecider) -> list[ReversalRequestOut]:
    return views.pending_reversals(session)


@router.post("/reversal-requests/{request_id}/decision", response_model=ReversalRequestOut)
def decide_reversal(
    request_id: int,
    body: ReversalDecisionIn,
    request: Request,
    session: DbSession,
    user: ReversalDecider,
) -> ReversalRequestOut:
    found = reversals.decide_reversal(
        session,
        user,
        request_id,
        body.decision,
        body.reason,
        now=clock.utc_now(),
        ip=client_ip(request),
    )
    return views.reversal_requests_out(session, [found])[0]


@router.get("/drivers/{driver_id}/advance", response_model=AdvanceOut)
def driver_advance(driver_id: int, session: DbSession, user: SignedIn) -> AdvanceOut:
    driver = get_driver(session, driver_id)
    require_money_view(user, driver)
    return views.advance_out(session, driver.id)


@router.get("/advance/pending", response_model=list[AdvanceTransactionOut])
def advance_pending(session: DbSession, user: AdvanceDecider) -> list[AdvanceTransactionOut]:
    return views.pending_advance(session)


def _one(session: Session, tx: AdvanceTransaction) -> AdvanceTransactionOut:
    return views.transactions_out(session, [tx])[0]


@router.post(
    "/advance/adjustments",
    response_model=AdvanceTransactionOut,
    status_code=status.HTTP_201_CREATED,
)
def advance_adjustment(
    body: AdvanceAdjustmentIn, request: Request, session: DbSession, user: Requester
) -> AdvanceTransactionOut:
    tx = advance.request_advance_adjustment(
        session,
        user,
        body.driver_id,
        body.items,
        body.reason,
        now=clock.utc_now(),
        ip=client_ip(request),
    )
    return _one(session, tx)


@router.post(
    "/advance/refunds", response_model=AdvanceTransactionOut, status_code=status.HTTP_201_CREATED
)
def advance_refund(
    body: AdvanceRefundIn, request: Request, session: DbSession, user: Requester
) -> AdvanceTransactionOut:
    tx = advance.request_refund(
        session,
        user,
        body.driver_id,
        body.amount_paise,
        body.reason,
        now=clock.utc_now(),
        ip=client_ip(request),
    )
    return _one(session, tx)


@router.post("/advance/{transaction_id}/decision", response_model=AdvanceTransactionOut)
def advance_decision(
    transaction_id: int,
    body: AdvanceDecisionIn,
    request: Request,
    session: DbSession,
    user: AdvanceDecider,
) -> AdvanceTransactionOut:
    tx = advance.decide_advance(
        session,
        user,
        transaction_id,
        body.decision,
        body.reason,
        now=clock.utc_now(),
        ip=client_ip(request),
    )
    return _one(session, tx)
