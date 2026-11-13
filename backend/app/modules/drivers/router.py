"""Driver endpoints (docs/api.md "Drivers"). Business rules live in the service."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import AppError
from app.core.files import MAX_UPLOAD_BYTES
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.drivers import service
from app.modules.drivers.schemas import (
    DriverCreate,
    DriverListItem,
    DriverOut,
    DriverUpdate,
    ManagerChange,
    ManagerHistoryOut,
    OptionalReasonIn,
    RestrictionCreate,
    RestrictionOut,
    StatusChange,
    TimelineEntry,
    UserRef,
)

router = APIRouter(tags=["drivers"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Creator = Annotated[CurrentUser, Depends(require(Permission.DRIVERS_CREATE))]
Reassigner = Annotated[CurrentUser, Depends(require(Permission.DRIVERS_REASSIGN))]
Restricter = Annotated[CurrentUser, Depends(require(Permission.DRIVERS_RESTRICT))]


def read_upload(file: UploadFile) -> bytes:
    """Read at most MAX_UPLOAD_BYTES (+1 to detect more) from an upload. Synchronous on purpose:
    the routes are plain `def` (run in the thread pool) because the database session is sync."""
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("FILE_TOO_LARGE", "The file is larger than 10 MB.", status_code=422)
    return data


@router.get("/drivers", response_model=Page[DriverListItem])
def list_drivers(
    session: DbSession,
    user: SignedIn,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    account_status: Annotated[
        Literal["active", "suspended", "inactive"] | None, Query(alias="status")
    ] = None,
    managed_by: int | None = None,
    mine: bool = False,
    kyc: Literal["verified", "not_verified"] | None = None,
) -> Page[DriverListItem]:
    return service.list_drivers(
        session,
        user,
        params,
        search=search,
        status=account_status,
        managed_by=managed_by,
        mine=mine,
        kyc=kyc,
    )


@router.post("/drivers", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(
    body: DriverCreate, request: Request, session: DbSession, user: Creator
) -> DriverOut:
    driver = service.create_driver(session, user, body, ip=client_ip(request))
    return service.driver_out(session, user, driver)


@router.get("/drivers/managers", response_model=list[UserRef])
def manager_options(session: DbSession, _: SignedIn) -> list[UserRef]:
    """Active users who can manage drivers (for the "Managed by" filter and Change manager)."""
    return service.manager_options(session)


@router.get("/drivers/{driver_id}", response_model=DriverOut)
def get_driver(driver_id: int, session: DbSession, user: SignedIn) -> DriverOut:
    return service.driver_out(session, user, service.get_driver(session, driver_id))


@router.patch("/drivers/{driver_id}", response_model=DriverOut)
def update_driver(
    driver_id: int, body: DriverUpdate, request: Request, session: DbSession, user: SignedIn
) -> DriverOut:
    driver = service.update_driver(session, user, driver_id, body, ip=client_ip(request))
    return service.driver_out(session, user, driver)


@router.post("/drivers/{driver_id}/photo", response_model=DriverOut)
def upload_photo(
    driver_id: int,
    request: Request,
    session: DbSession,
    user: SignedIn,
    file: Annotated[UploadFile, File()],
) -> DriverOut:
    data = read_upload(file)
    driver = service.set_photo(
        session, request.app.state.settings, user, driver_id, data, ip=client_ip(request)
    )
    return service.driver_out(session, user, driver)


@router.post("/drivers/{driver_id}/manager", response_model=DriverOut)
def change_manager(
    driver_id: int, body: ManagerChange, request: Request, session: DbSession, owner: Reassigner
) -> DriverOut:
    driver = service.change_manager(
        session,
        owner,
        driver_id,
        staff_id=body.staff_id,
        reason=body.reason,
        ip=client_ip(request),
    )
    return service.driver_out(session, owner, driver)


@router.get("/drivers/{driver_id}/manager-history", response_model=list[ManagerHistoryOut])
def manager_history(driver_id: int, session: DbSession, _: SignedIn) -> list[ManagerHistoryOut]:
    return service.manager_history(session, driver_id)


@router.get("/drivers/{driver_id}/timeline", response_model=list[TimelineEntry])
def timeline(driver_id: int, session: DbSession, user: SignedIn) -> list[TimelineEntry]:
    return service.timeline(session, user, driver_id)


@router.post("/drivers/{driver_id}/suspend", response_model=DriverOut)
def suspend(
    driver_id: int, body: StatusChange, request: Request, session: DbSession, user: Restricter
) -> DriverOut:
    driver = service.set_account_status(
        session, user, driver_id, status="suspended", reason=body.reason, ip=client_ip(request)
    )
    return service.driver_out(session, user, driver)


@router.post("/drivers/{driver_id}/reactivate", response_model=DriverOut)
def reactivate(
    driver_id: int,
    body: OptionalReasonIn,
    request: Request,
    session: DbSession,
    user: Restricter,
) -> DriverOut:
    driver = service.set_account_status(
        session, user, driver_id, status="active", reason=body.reason, ip=client_ip(request)
    )
    return service.driver_out(session, user, driver)


@router.get("/drivers/{driver_id}/restrictions", response_model=list[RestrictionOut])
def list_restrictions(driver_id: int, session: DbSession, _: SignedIn) -> list[RestrictionOut]:
    return [
        service.restriction_out(session, r) for r in service.list_restrictions(session, driver_id)
    ]


@router.post(
    "/drivers/{driver_id}/restrictions",
    response_model=RestrictionOut,
    status_code=status.HTTP_201_CREATED,
)
def place_restriction(
    driver_id: int,
    body: RestrictionCreate,
    request: Request,
    session: DbSession,
    user: Restricter,
) -> RestrictionOut:
    restriction = service.place_restriction(
        session,
        user,
        driver_id,
        reason=body.reason,
        is_blocking=body.is_blocking,
        ip=client_ip(request),
    )
    return service.restriction_out(session, restriction)


@router.post("/restrictions/{restriction_id}/lift", response_model=RestrictionOut)
def lift_restriction(
    restriction_id: int,
    body: OptionalReasonIn,
    request: Request,
    session: DbSession,
    user: Restricter,
) -> RestrictionOut:
    restriction = service.lift_restriction(
        session, user, restriction_id, reason=body.reason, ip=client_ip(request)
    )
    return service.restriction_out(session, restriction)
