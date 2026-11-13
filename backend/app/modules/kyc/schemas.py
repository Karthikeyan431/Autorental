"""KYC requests and responses (docs/kyc.md). No field ever carries a full Aadhaar number, and
the licence number is never returned: only its last four characters."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.identifiers import NoAadhaarStr
from app.modules.documents.schemas import DocumentOut
from app.modules.drivers.schemas import UserRef

CheckType = Literal["identity", "licence"]
Method = Literal["uidai_qr", "uidai_app_attested", "parivahan_lookup", "manual", "demo"]
ShortText = Annotated[NoAadhaarStr, Field(min_length=1, max_length=200)]
Reason = Annotated[NoAadhaarStr, Field(min_length=1, max_length=500)]


# --- Consents -------------------------------------------------------------------------------------


class ConsentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["kyc", "aadhaar_qr"]
    notice_version: Annotated[str, Field(min_length=1, max_length=50)]
    method: Literal["in_person_signed", "in_person_checkbox"]


class ConsentWithdraw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[NoAadhaarStr, Field(max_length=500)] | None = None


class ConsentOut(BaseModel):
    id: int
    driver_id: int
    purpose: str
    notice_version: str
    method: str
    captured_by: UserRef
    captured_at: datetime
    withdrawn_at: datetime | None
    withdrawn_by: UserRef | None
    withdrawal_reason: str | None


# --- Attempts -------------------------------------------------------------------------------------


class AttemptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Method


class IdentityDetailsIn(BaseModel):
    """Manual identity: the masked document's type, last 4 digits, name and date/year of birth."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["masked_aadhaar", "voter_id", "passport"]
    id_last4: Annotated[str, Field(pattern=r"^[0-9]{4}$")]
    name_on_document: ShortText
    dob_or_yob: Annotated[str, Field(pattern=r"^[0-9]{4}(-[0-9]{2}-[0-9]{2})?$")]
    gender: Annotated[NoAadhaarStr, Field(max_length=30)] | None = None


class IdentityDetailsOut(BaseModel):
    document_type: str
    id_last4: str
    name_on_document: str | None
    dob_or_yob: str | None
    gender: str | None


VehicleClass = Annotated[NoAadhaarStr, Field(min_length=1, max_length=30)]


class LicenceDetailsIn(BaseModel):
    """Manual licence: the details typed from the card (front and back are uploaded)."""

    model_config = ConfigDict(extra="forbid")

    licence_number: Annotated[str, Field(min_length=1, max_length=40)]
    name_on_licence: ShortText
    date_of_birth: date | None = None
    issue_date: date | None = None
    valid_until_non_transport: date | None = None
    valid_until_transport: date | None = None
    vehicle_classes: Annotated[list[VehicleClass], Field(min_length=1, max_length=12)]
    issuing_authority: ShortText | None = None

    @model_validator(mode="after")
    def _one_validity_date(self) -> "LicenceDetailsIn":
        if self.valid_until_non_transport is None and self.valid_until_transport is None:
            raise ValueError("Enter at least one validity date (transport or non-transport).")
        return self


class LicenceDetailsOut(BaseModel):
    licence_number_masked: str
    name_on_licence: str | None
    date_of_birth: date | None
    issue_date: date | None
    valid_until_non_transport: date | None
    valid_until_transport: date | None
    valid_until: date | None
    vehicle_classes: list[str]
    issuing_authority: str | None


class ChecklistItem(BaseModel):
    key: str
    label: str
    required: bool


class KycEventOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    actor: UserRef | None
    at: datetime
    reason: str | None


class AttemptOut(BaseModel):
    id: int
    driver_id: int
    check_type: str
    attempt_no: int
    method: str
    status: str
    is_current: bool
    is_simulated: bool
    submitted_at: datetime | None
    reviewed_by: UserRef | None
    reviewed_at: datetime | None
    decision_reason: str | None
    review_checklist: dict[str, Any] | None
    reopened_from_id: int | None
    created_by: UserRef | None
    created_at: datetime
    identity_details: IdentityDetailsOut | None
    licence_details: LicenceDetailsOut | None
    documents: list[DocumentOut]
    events: list[KycEventOut]
    checklist: list[ChecklistItem]
    required_documents: list[str]


class DriverKycOut(BaseModel):
    driver_id: int
    identity: AttemptOut | None
    licence: AttemptOut | None
    history: list[AttemptOut]
    consents: list[ConsentOut]
    has_kyc_consent: bool
    accepted_id_types: list[str]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "resubmit"]
    checklist: dict[str, bool] = Field(default_factory=dict)
    reason: Reason | None = None


class ReopenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


# --- Queue and eligibility ------------------------------------------------------------------------

Bucket = Literal["pending", "under_review", "resubmission", "rejected", "expiring"]


class QueueDriver(BaseModel):
    id: int
    code: str
    full_name: str
    managed_by: UserRef


class QueueItem(BaseModel):
    driver: QueueDriver
    check_type: str
    bucket: str
    attempt_id: int | None
    attempt_no: int | None
    status: str | None
    submitted_at: datetime | None
    updated_at: datetime | None
    licence_valid_until: date | None


class QueueCounts(BaseModel):
    pending: int
    under_review: int
    resubmission: int
    rejected: int
    expiring: int


class EligibilityOut(BaseModel):
    driver_id: int
    on_date: date
    ok: bool
    reasons: list[str]
    messages: list[str]
    licence_valid_until: date | None
