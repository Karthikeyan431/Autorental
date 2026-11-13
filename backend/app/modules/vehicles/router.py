"""Auto endpoints (docs/api.md "Vehicles"). Reading is open to every signed-in user; writes need
`vehicles.manage`."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.identifiers import NoAadhaarStr
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.drivers.router import read_upload
from app.modules.vehicles import service
from app.modules.vehicles.schemas import (
    MaintenanceCreate,
    MaintenanceOut,
    PaperKind,
    PaperOut,
    StatusChange,
    VehicleCreate,
    VehicleOut,
    VehicleStatus,
    VehicleSummary,
    VehicleUpdate,
)

router = APIRouter(tags=["vehicles"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]
Manager = Annotated[CurrentUser, Depends(require(Permission.VEHICLES_MANAGE))]


class PaperForm(BaseModel):
    """The multipart form fields of a paper, validated like a JSON body."""

    model_config = ConfigDict(extra="forbid")

    kind: PaperKind
    number: Annotated[NoAadhaarStr, Field(max_length=60)] | None = None
    valid_from: date | None = None
    valid_until: date

    @model_validator(mode="after")
    def _from_before_until(self) -> "PaperForm":
        if self.valid_from is not None and self.valid_from > self.valid_until:
            raise ValueError("Valid from cannot be after valid until.")
        return self


@router.get("/vehicles", response_model=Page[VehicleOut])
def list_vehicles(
    session: DbSession,
    user: SignedIn,
    params: Annotated[PageParams, Depends(page_params)],
    vehicle_status: Annotated[VehicleStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[VehicleOut]:
    return service.list_vehicles(session, params, status=vehicle_status, search=search)


@router.get("/vehicles/summary", response_model=VehicleSummary)
def vehicle_summary(session: DbSession, user: SignedIn) -> VehicleSummary:
    return service.summary(session)


@router.post("/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    body: VehicleCreate, request: Request, session: DbSession, user: Manager
) -> VehicleOut:
    vehicle = service.create_vehicle(session, user, body, ip=client_ip(request))
    return service.vehicle_out(session, vehicle)


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, session: DbSession, user: SignedIn) -> VehicleOut:
    return service.vehicle_out(session, service.get_vehicle(session, vehicle_id))


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int, body: VehicleUpdate, request: Request, session: DbSession, user: Manager
) -> VehicleOut:
    vehicle = service.update_vehicle(session, user, vehicle_id, body, ip=client_ip(request))
    return service.vehicle_out(session, vehicle)


@router.post("/vehicles/{vehicle_id}/status", response_model=VehicleOut)
def change_status(
    vehicle_id: int, body: StatusChange, request: Request, session: DbSession, user: Manager
) -> VehicleOut:
    vehicle = service.change_status(session, user, vehicle_id, body, ip=client_ip(request))
    return service.vehicle_out(session, vehicle)


@router.get("/vehicles/{vehicle_id}/compliance", response_model=list[PaperOut])
def list_papers(vehicle_id: int, session: DbSession, user: SignedIn) -> list[PaperOut]:
    return service.list_papers(session, vehicle_id)


@router.post(
    "/vehicles/{vehicle_id}/compliance",
    response_model=PaperOut,
    status_code=status.HTTP_201_CREATED,
)
def add_paper(
    vehicle_id: int,
    request: Request,
    session: DbSession,
    user: Manager,
    kind: Annotated[str, Form(max_length=20)],
    valid_until: Annotated[str, Form(max_length=10)],
    number: Annotated[str | None, Form(max_length=60)] = None,
    valid_from: Annotated[str | None, Form(max_length=10)] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> PaperOut:
    form = PaperForm.model_validate(
        {
            "kind": kind,
            "number": number or None,
            "valid_from": valid_from or None,
            "valid_until": valid_until,
        }
    )
    data = read_upload(file) if file is not None else None
    paper = service.add_paper(
        session,
        request.app.state.settings,
        user,
        vehicle_id,
        service.PaperInput(
            kind=form.kind,
            number=form.number,
            valid_from=form.valid_from,
            valid_until=form.valid_until,
        ),
        file=data,
        ip=client_ip(request),
    )
    return next(p for p in service.list_papers(session, vehicle_id) if p.id == paper.id)


@router.get("/vehicles/{vehicle_id}/maintenance", response_model=list[MaintenanceOut])
def list_maintenance(vehicle_id: int, session: DbSession, user: SignedIn) -> list[MaintenanceOut]:
    return service.list_maintenance(session, vehicle_id)


@router.post(
    "/vehicles/{vehicle_id}/maintenance",
    response_model=MaintenanceOut,
    status_code=status.HTTP_201_CREATED,
)
def add_maintenance(
    vehicle_id: int,
    body: MaintenanceCreate,
    request: Request,
    session: DbSession,
    user: Manager,
) -> MaintenanceOut:
    return service.add_maintenance(session, user, vehicle_id, body, ip=client_ip(request))
