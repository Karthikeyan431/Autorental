"""Auto requests and responses (docs/api.md "Vehicles"). Money is integer paise."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from app.core.identifiers import NoAadhaarStr, contains_aadhaar_like
from app.modules.drivers.schemas import UserRef

VehicleStatus = Literal["available", "rented", "maintenance", "inactive"]
FuelType = Literal["cng", "lpg", "petrol", "diesel", "electric"]
PaperKind = Literal["insurance", "fitness", "permit", "pollution"]
PaperState = Literal["ok", "expiring", "expired"]
ShortText = Annotated[NoAadhaarStr, Field(min_length=1, max_length=100)]
Notes = Annotated[NoAadhaarStr, Field(max_length=1000)]

_REGISTRATION = re.compile(r"^[A-Z0-9]{4,12}$")


def normalise_registration(value: str) -> str:
    """Upper case, without spaces or hyphens: "xx 00-tt 0101" -> "XX00TT0101". A registration
    number always has letters (the state code), so an all-digit value is refused: it could be a
    full Aadhaar number (hard constraint 5)."""
    normalised = re.sub(r"[\s-]+", "", value).upper()
    if contains_aadhaar_like(value) or normalised.isdigit():
        raise ValueError("A registration number has letters; a 12-digit number is not allowed.")
    if not _REGISTRATION.fullmatch(normalised):
        raise ValueError("Enter the registration number: 4 to 12 letters and digits.")
    return normalised


class _RegistrationMixin(BaseModel):
    @field_validator("registration_number", mode="before", check_fields=False)
    @classmethod
    def _normalise(cls, value: object) -> object:
        return normalise_registration(value) if isinstance(value, str) else value


class VehicleCreate(_RegistrationMixin):
    model_config = ConfigDict(extra="forbid")

    registration_number: str
    make: ShortText
    model: ShortText
    year: Annotated[int, Field(ge=1980, le=2100)] | None = None
    fuel_type: FuelType | None = None
    notes: Notes | None = None


class VehicleUpdate(_RegistrationMixin):
    model_config = ConfigDict(extra="forbid")

    registration_number: str | None = None
    make: ShortText | None = None
    model: ShortText | None = None
    year: Annotated[int, Field(ge=1980, le=2100)] | None = None
    fuel_type: FuelType | None = None
    notes: Notes | None = None


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `rented` is accepted here only so the refusal can name it (VEHICLE_STATUS_NOT_ALLOWED).
    status: VehicleStatus
    reason: Annotated[NoAadhaarStr, Field(max_length=500)] | None = None


class PaperOut(BaseModel):
    id: int
    kind: str
    number: str | None
    valid_from: date | None
    valid_until: date
    document_id: int | None
    # For the viewer: image/jpeg, image/png or application/pdf.
    document_mime_type: str | None
    state: PaperState
    recorded_by: UserRef | None
    created_at: datetime


class VehicleOut(BaseModel):
    id: int
    registration_number: str
    make: str
    model: str
    year: int | None
    fuel_type: str | None
    status: str
    # Can start an agreement (Week 5 checks again under a lock): available only.
    selectable: bool
    notes: str | None
    # The current paper of each kind (latest valid_until).
    papers: list[PaperOut]
    created_by: UserRef | None
    created_at: datetime


class VehicleSummary(BaseModel):
    available: int
    rented: int
    maintenance: int
    inactive: int
    papers_expiring: int
    papers_expired: int


class MaintenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_on: date
    ended_on: date | None = None
    description: Annotated[NoAadhaarStr, Field(min_length=1, max_length=1000)]
    cost_paise: Annotated[StrictInt, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _ended_after_started(self) -> "MaintenanceCreate":
        if self.ended_on is not None and self.ended_on < self.started_on:
            raise ValueError("The end date cannot be before the start date.")
        return self


class MaintenanceOut(BaseModel):
    id: int
    vehicle_id: int
    started_on: date
    ended_on: date | None
    description: str
    cost_paise: int | None
    recorded_by: UserRef | None
    created_at: datetime
