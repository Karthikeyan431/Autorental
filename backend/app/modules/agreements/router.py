"""Agreement endpoints (docs/api.md "Agreements"). Reading is open to every signed-in user;
creating, activating, ending, cancelling, printing and uploading the signed copy need
`agreements.manage` (staff on by default), for any driver (Week 5 plan approval)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.agreements import service
from app.modules.agreements.schemas import (
    AgreementCancel,
    AgreementCreate,
    AgreementEnd,
    AgreementOut,
    AgreementStatus,
    EligibilityOut,
    EndOut,
)
from app.modules.drivers.router import read_upload

router = APIRouter(tags=["agreements"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Manager = Annotated[CurrentUser, Depends(require(Permission.AGREEMENTS_MANAGE))]


@router.get("/agreements", response_model=Page[AgreementOut])
def list_agreements(
    session: DbSession,
    user: SignedIn,
    params: Annotated[PageParams, Depends(page_params)],
    agreement_status: Annotated[AgreementStatus | None, Query(alias="status")] = None,
    driver_id: int | None = None,
    vehicle_id: int | None = None,
    search: Annotated[str | None, Query(max_length=30)] = None,
) -> Page[AgreementOut]:
    return service.list_agreements(
        session,
        params,
        status=agreement_status,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        search=search,
    )


@router.get("/agreements/eligibility", response_model=EligibilityOut)
def eligibility(
    request: Request,
    session: DbSession,
    user: Manager,
    driver_id: int,
    vehicle_id: int,
    start_date: date,
) -> EligibilityOut:
    return service.eligibility_preview(
        session,
        user,
        driver_id,
        vehicle_id,
        start_date,
        settings=request.app.state.settings,
    )


@router.post("/agreements", response_model=AgreementOut, status_code=status.HTTP_201_CREATED)
def create_agreement(
    body: AgreementCreate, request: Request, session: DbSession, user: Manager
) -> AgreementOut:
    agreement = service.create_draft(session, user, body, ip=client_ip(request))
    return service.agreement_out(session, agreement)


@router.get("/agreements/{agreement_id}", response_model=AgreementOut)
def get_agreement(agreement_id: int, session: DbSession, user: SignedIn) -> AgreementOut:
    return service.agreement_out(session, service.get_agreement(session, agreement_id))


@router.post("/agreements/{agreement_id}/activate", response_model=AgreementOut)
def activate(
    agreement_id: int, request: Request, session: DbSession, user: Manager
) -> AgreementOut:
    agreement = service.activate_agreement(
        session,
        user,
        agreement_id,
        settings=request.app.state.settings,
        ip=client_ip(request),
    )
    return service.agreement_out(session, agreement)


@router.post("/agreements/{agreement_id}/end", response_model=EndOut)
def end(
    agreement_id: int, body: AgreementEnd, request: Request, session: DbSession, user: Manager
) -> EndOut:
    result = service.end_agreement(session, user, agreement_id, body, ip=client_ip(request))
    return EndOut(
        agreement=service.agreement_out(session, result.agreement),
        waivers_created=len(result.waivers),
    )


@router.post("/agreements/{agreement_id}/cancel", response_model=AgreementOut)
def cancel(
    agreement_id: int, body: AgreementCancel, request: Request, session: DbSession, user: Manager
) -> AgreementOut:
    agreement = service.cancel_agreement(session, user, agreement_id, body, ip=client_ip(request))
    return service.agreement_out(session, agreement)


@router.get(
    "/agreements/{agreement_id}/print",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def print_agreement(agreement_id: int, session: DbSession, user: Manager) -> Response:
    agreement = service.get_agreement(session, agreement_id)
    pdf = service.print_agreement(session, agreement)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # D40: PDFs are always downloaded, never shown inline.
            "Content-Disposition": f'attachment; filename="agreement-{agreement.agreement_no}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/agreements/{agreement_id}/signed-copy", response_model=AgreementOut)
def upload_signed_copy(
    agreement_id: int,
    request: Request,
    session: DbSession,
    user: Manager,
    file: Annotated[UploadFile, File()],
) -> AgreementOut:
    agreement = service.upload_signed_copy(
        session,
        request.app.state.settings,
        user,
        agreement_id,
        data=read_upload(file),
        ip=client_ip(request),
    )
    return service.agreement_out(session, agreement)
