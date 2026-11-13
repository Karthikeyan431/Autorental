"""Driver requests and responses. Every free-text field refuses a full Aadhaar-like number."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.identifiers import NoAadhaarStr
from app.core.phone import normalise_mobile
from app.core.time import business_date

Name = Annotated[NoAadhaarStr, Field(min_length=1, max_length=120)]
Address = Annotated[NoAadhaarStr, Field(min_length=1, max_length=500)]
Reason = Annotated[NoAadhaarStr, Field(min_length=1, max_length=500)]
OptionalReason = Annotated[NoAadhaarStr, Field(max_length=500)] | None
PaymentRhythm = Literal["daily", "weekly"]


def _clean_text(value: Any) -> Any:
    return " ".join(value.split()) if isinstance(value, str) else value


def _mobile(value: Any) -> Any:
    if value is None or value == "":
        return None
    return normalise_mobile(str(value))  # ValueError -> 422 without echoing the value


class DriverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Name
    mobile: str
    alt_mobile: str | None = None
    address: Address
    date_of_birth: date
    emergency_name: Name | None = None
    emergency_mobile: str | None = None
    payment_rhythm: PaymentRhythm = "daily"

    _clean = field_validator("full_name", "address", "emergency_name", mode="before")(_clean_text)
    _mobiles = field_validator("mobile", "alt_mobile", "emergency_mobile", mode="before")(_mobile)

    @field_validator("date_of_birth")
    @classmethod
    def _in_the_past(cls, value: date) -> date:
        if value >= business_date():
            raise ValueError("The date of birth must be in the past.")
        return value


def _blank_keeps(value: Any) -> Any:
    """Masked fields are not pre-filled in the edit form: blank means "keep the current value"
    (N17), so an empty or whitespace-only value becomes None."""
    if isinstance(value, str):
        cleaned = " ".join(value.split())
        return cleaned or None
    return value


class DriverUpdate(BaseModel):
    """The fields staff may change. `created_by`, `managed_by`, `code` and status are not here:
    an attempt to send them is refused (422). The masked fields (address, date of birth) may be
    sent only by the owner or the current manager; blank or null keeps the current value."""

    model_config = ConfigDict(extra="forbid")

    full_name: Name | None = None
    mobile: str | None = None
    alt_mobile: str | None = None
    address: Address | None = None
    date_of_birth: date | None = None
    emergency_name: Name | None = None
    emergency_mobile: str | None = None
    payment_rhythm: PaymentRhythm | None = None

    _clean = field_validator("full_name", "emergency_name", mode="before")(_clean_text)
    _masked = field_validator("address", "date_of_birth", mode="before")(_blank_keeps)
    _mobiles = field_validator("mobile", "alt_mobile", "emergency_mobile", mode="before")(_mobile)

    @field_validator("date_of_birth")
    @classmethod
    def _in_the_past(cls, value: date | None) -> date | None:
        if value is not None and value >= business_date():
            raise ValueError("The date of birth must be in the past.")
        return value


class UserRef(BaseModel):
    id: int
    name: str


class DriverOut(BaseModel):
    id: int
    code: str
    full_name: str
    mobile: str
    alt_mobile: str | None
    # The address and date of birth are never returned; "Show" uses POST /drivers/{id}/reveal.
    masked_fields: list[str]
    can_reveal: bool
    emergency_name: str | None
    emergency_mobile: str | None
    photo_document_id: int | None
    account_status: str
    status_reason: str | None
    payment_rhythm: str
    registered_at: datetime
    created_by: UserRef
    managed_by: UserRef
    managed_since: datetime | None
    # KYC summary: null for users who cannot see this driver's KYC.
    identity_status: str | None
    licence_status: str | None
    can_edit: bool
    can_view_kyc: bool


class DriverListItem(BaseModel):
    id: int
    code: str
    full_name: str
    mobile: str
    account_status: str
    photo_document_id: int | None
    created_by: UserRef
    managed_by: UserRef
    identity_status: str | None
    licence_status: str | None


class ManagerChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_id: int
    reason: Reason


class ManagerHistoryOut(BaseModel):
    id: int
    staff: UserRef
    from_at: datetime
    to_at: datetime | None
    changed_by: UserRef
    reason: str | None


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class OptionalReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: OptionalReason = None


class RestrictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    is_blocking: bool = True


class RestrictionOut(BaseModel):
    id: int
    driver_id: int
    reason: str
    is_blocking: bool
    placed_by: UserRef
    placed_at: datetime
    lifted_by: UserRef | None
    lifted_at: datetime | None
    lift_reason: str | None


RevealField = Annotated[str, Field(min_length=1, max_length=40)]


class RevealIn(BaseModel):
    """One masked field. KYC fields come from the current attempt unless `attempt_id` names an
    older attempt of the same driver. An unknown field gives 404 (not 422)."""

    model_config = ConfigDict(extra="forbid")

    field: RevealField
    attempt_id: int | None = None


class RevealOut(BaseModel):
    field: str
    value: str


class TimelineEntry(BaseModel):
    id: int
    at: datetime
    action: str
    entity_type: str
    entity_id: int | None
    actor: UserRef | None
    reason: str | None
    before: Any = None
    after: Any = None
