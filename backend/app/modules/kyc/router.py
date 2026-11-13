"""Consent, KYC and eligibility endpoints (docs/api.md "Consents", "KYC")."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.documents.schemas import DocumentOut, document_out
from app.modules.drivers.router import read_upload
from app.modules.kyc import service
from app.modules.kyc.eligibility import REASON_MESSAGES
from app.modules.kyc.schemas import (
    AttemptCreate,
    AttemptOut,
    Bucket,
    CheckType,
    ConsentCreate,
    ConsentOut,
    ConsentWithdraw,
    DecisionIn,
    DriverKycOut,
    EligibilityOut,
    IdentityDetailsIn,
    LicenceDetailsIn,
    QueueCounts,
    QueueItem,
    ReopenIn,
)

router = APIRouter(tags=["kyc"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Decider = Annotated[CurrentUser, Depends(require(Permission.KYC_DECIDE))]
Reopener = Annotated[CurrentUser, Depends(require(Permission.KYC_REOPEN))]


# --- Consents -------------------------------------------------------------------------------------


@router.post(
    "/drivers/{driver_id}/consents",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
)
def record_consent(
    driver_id: int, body: ConsentCreate, request: Request, session: DbSession, user: SignedIn
) -> ConsentOut:
    consent = service.record_consent(
        session,
        user,
        driver_id,
        purpose=body.purpose,
        notice_version=body.notice_version,
        method=body.method,
        ip=client_ip(request),
    )
    return service.consent_out(session, consent)


@router.post("/consents/{consent_id}/withdraw", response_model=ConsentOut)
def withdraw_consent(
    consent_id: int, body: ConsentWithdraw, request: Request, session: DbSession, user: SignedIn
) -> ConsentOut:
    consent = service.withdraw_consent(
        session, user, consent_id, reason=body.reason, ip=client_ip(request)
    )
    return service.consent_out(session, consent)


# --- KYC ------------------------------------------------------------------------------------------


@router.get("/drivers/{driver_id}/kyc", response_model=DriverKycOut)
def driver_kyc(driver_id: int, session: DbSession, user: SignedIn) -> DriverKycOut:
    return service.driver_kyc(session, user, driver_id)


@router.post(
    "/drivers/{driver_id}/kyc/{check_type}/attempts",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
def start_attempt(
    driver_id: int,
    check_type: CheckType,
    body: AttemptCreate,
    request: Request,
    session: DbSession,
    user: SignedIn,
) -> AttemptOut:
    check = service.start_attempt(
        session,
        user,
        driver_id,
        check_type=check_type,
        method=body.method,
        ip=client_ip(request),
    )
    return service.attempt_out(session, check)


@router.get("/kyc/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(attempt_id: int, session: DbSession, user: SignedIn) -> AttemptOut:
    return service.get_attempt(session, user, attempt_id)


@router.put("/kyc/attempts/{attempt_id}/identity-details", response_model=AttemptOut)
def save_identity_details(
    attempt_id: int,
    body: IdentityDetailsIn,
    request: Request,
    session: DbSession,
    user: SignedIn,
) -> AttemptOut:
    check = service.save_identity_details(session, user, attempt_id, body, ip=client_ip(request))
    return service.attempt_out(session, check)


@router.put("/kyc/attempts/{attempt_id}/licence-details", response_model=AttemptOut)
def save_licence_details(
    attempt_id: int,
    body: LicenceDetailsIn,
    request: Request,
    session: DbSession,
    user: SignedIn,
) -> AttemptOut:
    check = service.save_licence_details(
        session, request.app.state.settings, user, attempt_id, body, ip=client_ip(request)
    )
    return service.attempt_out(session, check)


@router.post(
    "/kyc/attempts/{attempt_id}/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    attempt_id: int,
    request: Request,
    session: DbSession,
    user: SignedIn,
    doc_type: Annotated[str, Form(max_length=30)],
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    data = read_upload(file)
    document = service.upload_attempt_document(
        session,
        request.app.state.settings,
        user,
        attempt_id,
        doc_type=doc_type,
        data=data,
        ip=client_ip(request),
    )
    return document_out(document)


@router.post("/kyc/attempts/{attempt_id}/submit", response_model=AttemptOut)
def submit_attempt(
    attempt_id: int, request: Request, session: DbSession, user: SignedIn
) -> AttemptOut:
    check = service.submit_attempt(session, user, attempt_id, ip=client_ip(request))
    return service.attempt_out(session, check)


@router.post("/kyc/attempts/{attempt_id}/decision", response_model=AttemptOut)
def decide_attempt(
    attempt_id: int, body: DecisionIn, request: Request, session: DbSession, user: Decider
) -> AttemptOut:
    check = service.decide_attempt(
        session,
        user,
        attempt_id,
        decision=body.decision,
        checklist=body.checklist,
        reason=body.reason,
        ip=client_ip(request),
    )
    return service.attempt_out(session, check)


@router.post(
    "/kyc/attempts/{attempt_id}/reopen",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
def reopen_attempt(
    attempt_id: int, body: ReopenIn, request: Request, session: DbSession, owner: Reopener
) -> AttemptOut:
    check = service.reopen_attempt(
        session, owner, attempt_id, reason=body.reason, ip=client_ip(request)
    )
    return service.attempt_out(session, check)


# --- Queue and eligibility ------------------------------------------------------------------------


@router.get("/kyc/queue", response_model=Page[QueueItem])
def kyc_queue(
    session: DbSession,
    user: SignedIn,
    params: Annotated[PageParams, Depends(page_params)],
    bucket: Bucket = "under_review",
    check_type: CheckType | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[QueueItem]:
    return service.queue(session, user, params, bucket=bucket, check_type=check_type, search=search)


@router.get("/kyc/queue/counts", response_model=QueueCounts)
def kyc_queue_counts(session: DbSession, user: SignedIn) -> QueueCounts:
    return service.queue_counts(session, user)


@router.get("/drivers/{driver_id}/eligibility", response_model=EligibilityOut)
def driver_eligibility(
    driver_id: int,
    request: Request,
    session: DbSession,
    user: SignedIn,
    on_date: date | None = None,
) -> EligibilityOut:
    result, day = service.eligibility(session, request.app.state.settings, user, driver_id, on_date)
    return EligibilityOut(
        driver_id=driver_id,
        on_date=day,
        ok=result.ok,
        reasons=result.reasons,
        messages=[REASON_MESSAGES[r] for r in result.reasons],
        licence_valid_until=result.licence_valid_until,
    )
