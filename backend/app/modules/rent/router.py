"""Rent endpoints (docs/api.md "Rent").

* `GET /drivers/{id}/ledger`: the owner, the driver's current manager and `reports.all`; anyone
  else gets 404 (N1, D54).
* `GET /rent/overdue`, `GET /rent/summary`, `GET /adjustments`: business-wide for the owner and
  `reports.all`, otherwise the staff member's own drivers.
* Adjustments: `adjustments.request` (staff on) to ask, `adjustments.decide` (owner only) to
  decide.
* `POST /jobs/accrue`: the owner runs accrual now (`settings.manage`, owner only).
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.db import get_session
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.core.time import business_date
from app.modules.agreements.models import Agreement
from app.modules.drivers.service import get_driver
from app.modules.rent import adjustments as adjustment_service
from app.modules.rent.access import money_scope, require_money_view
from app.modules.rent.accrual import accrue
from app.modules.rent.ledger import driver_ledger, overdue_list, totals_for
from app.modules.rent.schemas import (
    AccrualOut,
    AdjustmentCreate,
    AdjustmentDecision,
    AdjustmentOut,
    LedgerOut,
    OverdueRow,
    RentSummary,
)

router = APIRouter(tags=["rent"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Requester = Annotated[CurrentUser, Depends(require(Permission.ADJUSTMENTS_REQUEST))]
Decider = Annotated[CurrentUser, Depends(require(Permission.ADJUSTMENTS_DECIDE))]
OwnerOnly = Annotated[CurrentUser, Depends(require(Permission.SETTINGS_MANAGE))]


@router.get("/drivers/{driver_id}/ledger", response_model=LedgerOut)
def ledger(
    driver_id: int,
    session: DbSession,
    user: SignedIn,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> LedgerOut:
    driver = get_driver(session, driver_id)
    require_money_view(user, driver)
    return driver_ledger(
        session, driver.id, now=clock.utc_now(), date_from=date_from, date_to=date_to
    )


@router.get("/rent/overdue", response_model=list[OverdueRow])
def overdue(session: DbSession, user: SignedIn) -> list[OverdueRow]:
    return overdue_list(session, now=clock.utc_now(), driver_ids=money_scope(session, user))


@router.get("/rent/summary", response_model=RentSummary)
def summary(session: DbSession, user: SignedIn) -> RentSummary:
    now = clock.utc_now()
    today = business_date(now)
    scope = money_scope(session, user)
    active = select(func.count(), func.coalesce(func.sum(Agreement.daily_rent_paise), 0)).where(
        Agreement.status == "active", Agreement.start_date <= today
    )
    if scope is not None:
        active = active.where(Agreement.driver_id.in_(scope))
    count, expected = session.execute(active).one()
    rows = overdue_list(session, now=now, driver_ids=scope)
    position = totals_for(session, now=now, driver_ids=scope)
    return RentSummary(
        scope="all" if scope is None else "own",
        as_of=now,
        rent_expected_today_paise=int(expected),
        active_agreements=int(count),
        overdue_drivers=len(rows),
        overdue_paise=position.overdue_paise,
        adjustments_pending=adjustment_service.count_pending(session, driver_ids=scope),
    )


@router.get("/adjustments", response_model=list[AdjustmentOut])
def list_adjustments(
    session: DbSession,
    user: SignedIn,
    adjustment_status: Annotated[Literal["pending"], Query(alias="status")] = "pending",
) -> list[AdjustmentOut]:
    items = adjustment_service.pending_adjustments(session, driver_ids=money_scope(session, user))
    return adjustment_service.adjustments_out(session, items)


@router.post(
    "/rent/charges/{charge_id}/adjustments",
    response_model=AdjustmentOut,
    status_code=status.HTTP_201_CREATED,
)
def request_adjustment(
    charge_id: int,
    body: AdjustmentCreate,
    request: Request,
    session: DbSession,
    user: Requester,
) -> AdjustmentOut:
    adjustment = adjustment_service.request_adjustment(
        session, user, charge_id, body, ip=client_ip(request)
    )
    return adjustment_service.adjustments_out(session, [adjustment])[0]


@router.post("/adjustments/{adjustment_id}/decision", response_model=AdjustmentOut)
def decide_adjustment(
    adjustment_id: int,
    body: AdjustmentDecision,
    request: Request,
    session: DbSession,
    user: Decider,
) -> AdjustmentOut:
    adjustment = adjustment_service.decide_adjustment(
        session, user, adjustment_id, body, ip=client_ip(request)
    )
    return adjustment_service.adjustments_out(session, [adjustment])[0]


@router.post("/jobs/accrue", response_model=AccrualOut)
def run_accrual(session: DbSession, user: OwnerOnly) -> AccrualOut:
    result = accrue(session, actor_id=user.id)
    return AccrualOut(charges_created=result.charges_created, agreements=result.agreements)
