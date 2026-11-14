"""Pay request endpoints (docs/api.md "Pay requests").

* `GET /pay-requests?date=&mine=`: the day's requests, scoped like D54 (the owner and
  `reports.all` see every driver, others their own); `mine=true` narrows to the drivers the
  viewer manages.
* `POST /pay-requests/generate`: `payrequests.send`; idempotent (rule 18).
* `GET /pay-requests/{id}`, `/qr.png`: the owner, the current manager and `reports.all`.
* `POST /pay-requests/{id}/sent`: `payrequests.send`, same visibility.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.db import get_session
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.core.time import business_date
from app.modules.pay_requests import service
from app.modules.pay_requests.schemas import GenerationOut, PayRequestOut
from app.modules.rent.access import money_scope

router = APIRouter(tags=["pay-requests"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Sender = Annotated[CurrentUser, Depends(require(Permission.PAYREQUESTS_SEND))]


@router.get("/pay-requests", response_model=list[PayRequestOut])
def list_pay_requests(
    session: DbSession,
    user: SignedIn,
    day: Annotated[date | None, Query(alias="date")] = None,
    mine: bool = False,
) -> list[PayRequestOut]:
    return service.list_pay_requests(
        session,
        user,
        day or business_date(clock.utc_now()),
        driver_ids=money_scope(session, user),
        mine=mine,
    )


@router.post("/pay-requests/generate", response_model=GenerationOut)
def generate(request: Request, session: DbSession, user: Sender) -> GenerationOut:
    result = service.generate_pay_requests(
        session, now=clock.utc_now(), actor_id=user.id, ip=client_ip(request)
    )
    return GenerationOut(
        created=result.created, superseded=result.superseded, unchanged=result.unchanged
    )


@router.get("/pay-requests/{request_id}", response_model=PayRequestOut)
def get_pay_request(request_id: int, session: DbSession, user: SignedIn) -> PayRequestOut:
    found = service.get_visible_request(session, user, request_id)
    return service.pay_requests_out(session, [found])[0]


@router.get(
    "/pay-requests/{request_id}/qr.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def qr(request_id: int, session: DbSession, user: SignedIn) -> Response:
    found = service.get_visible_request(session, user, request_id)
    return Response(
        content=service.qr_for(session, found),
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/pay-requests/{request_id}/sent", response_model=PayRequestOut)
def mark_sent(request_id: int, request: Request, session: DbSession, user: Sender) -> PayRequestOut:
    found = service.mark_sent(session, user, request_id, now=clock.utc_now(), ip=client_ip(request))
    return service.pay_requests_out(session, [found])[0]
