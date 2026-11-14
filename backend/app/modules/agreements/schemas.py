"""Validation and responses for agreements. Money is integer paise (hard constraint 4)."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.identifiers import NoAadhaarStr
from app.modules.drivers.schemas import UserRef

Paise = Annotated[int, Field(strict=True, ge=0)]
PositivePaise = Annotated[int, Field(strict=True, gt=0, le=10_000_000)]  # at most ₹1,00,000 a day
Reason = Annotated[NoAadhaarStr, Field(min_length=1, max_length=500)]
AgreementStatus = Literal["draft", "active", "ended", "cancelled"]


class AgreementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: int
    vehicle_id: int
    start_date: date
    daily_rent_paise: PositivePaise  # Q10: fixed for the whole agreement
    advance_required_paise: Paise = 0  # Q14; used from Week 6


class AgreementEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date  # the return day, charged in full (Q2)
    reason: Reason | None = None


class AgreementCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class VehicleBrief(BaseModel):
    id: int
    registration_number: str
    make: str
    model: str
    status: str


class DriverBrief(BaseModel):
    id: int
    code: str
    full_name: str
    managed_by: UserRef | None = None


class AgreementOut(BaseModel):
    id: int
    agreement_no: str
    status: AgreementStatus
    driver: DriverBrief
    vehicle: VehicleBrief
    start_date: date
    end_date: date | None
    daily_rent_paise: int
    advance_required_paise: int
    terms_version: str
    signed_document_id: int | None
    created_by: UserRef | None
    created_at: datetime
    activated_by: UserRef | None
    activated_at: datetime | None
    ended_by: UserRef | None
    ended_at: datetime | None
    end_reason: str | None
    cancelled_by: UserRef | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    # Q1: an ended agreement's auto can start a new agreement from the day after the return day.
    vehicle_available_from: date | None


class EndOut(BaseModel):
    agreement: AgreementOut
    waivers_created: int  # D52: pending waivers for charges after a late-recorded return day


class EligibilityReason(BaseModel):
    code: str
    message: str


class EligibilityOut(BaseModel):
    """The live panel on the New agreement screen: every reason, in a fixed order."""

    ok: bool
    reasons: list[EligibilityReason]
    vehicle_available_from: date | None = None
    max_backdate_days: int | None = None
