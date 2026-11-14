"""Payment, allocation, approval, reversal and advance schemas (docs/api.md "Payments",
"Advance"). Money is integer paise; floats are refused (strict ints)."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.drivers.schemas import UserRef

PaymentMethod = Literal["upi", "cash"]
PaymentPurpose = Literal["rent", "advance_deposit"]
PaymentStatus = Literal["awaiting_approval", "approved", "rejected", "reversed"]
Paise = Annotated[int, Field(strict=True, gt=0, le=10_000_000_00)]  # up to ₹1 crore
Reason = Annotated[str, Field(min_length=3, max_length=500)]

_REFERENCE = re.compile(r"^[A-Z0-9]{6,35}$")


def normalise_reference(value: str | None) -> str | None:
    """A UPI reference or UTR: upper-case letters and digits; spaces and symbols dropped."""
    if value is None:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned or None


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: int
    amount_paise: Paise
    method: PaymentMethod
    purpose: PaymentPurpose = "rent"
    reference: str | None = None
    received_on: date
    idempotency_key: Annotated[str, Field(min_length=8, max_length=100)]

    @field_validator("reference")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        cleaned = normalise_reference(value)
        if cleaned is not None and not _REFERENCE.fullmatch(cleaned):
            raise ValueError("A UPI reference has 6 to 35 letters and digits.")
        return cleaned


class AllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rent_charge_id: int
    amount_paise: Paise


class AllocationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[AllocationItem], Field(max_length=400)]


class AllocationOut(BaseModel):
    id: int
    rent_charge_id: int
    rent_date: date
    amount_paise: int
    confirmed_by: UserRef
    confirmed_at: datetime
    reversed_at: datetime | None
    reversal_reason: str | None


class SuggestedDay(BaseModel):
    rent_charge_id: int
    rent_date: date
    available_paise: int
    amount_paise: int


class SuggestionOut(BaseModel):
    unallocated_paise: int
    items: list[SuggestedDay]


class PaymentDriver(BaseModel):
    id: int
    code: str
    full_name: str


class PaymentOut(BaseModel):
    id: int
    driver: PaymentDriver
    agreement_id: int | None
    amount_paise: int
    method: PaymentMethod
    source: str
    purpose: PaymentPurpose
    reference: str | None
    received_on: date
    status: PaymentStatus
    recorded_by: UserRef
    recorded_at: datetime
    approved_by: UserRef | None
    approved_at: datetime | None
    rejected_by: UserRef | None
    rejected_at: datetime | None
    rejection_reason: str | None
    reversed_at: datetime | None
    receipt_no: str | None
    receipt_cancelled: bool
    pay_request_id: int | None
    proof_document_id: int | None
    allocated_paise: int
    unallocated_paise: int
    days_confirmed: bool
    allocations: list[AllocationOut]
    pending_reversal_id: int | None
    # What this viewer may do (the server checks again).
    can_confirm_days: bool


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[int], Field(min_length=1, max_length=100)]


class ApprovalResult(BaseModel):
    payment_id: int
    outcome: Literal["approved", "refused"]
    receipt_no: str | None = None
    code: str | None = None
    message: str | None = None


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ReversalRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ReversalDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: Annotated[str, Field(max_length=500)] | None = None


class ReversalRequestOut(BaseModel):
    id: int
    payment_id: int | None
    driver: PaymentDriver
    amount_paise: int
    receipt_no: str | None
    reason: str
    requested_by: UserRef
    requested_at: datetime
    decision: Literal["approved", "rejected"] | None
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_reason: str | None


AdvanceKind = Literal["deposit", "adjustment", "refund", "reversal"]
AdvanceStatus = Literal["pending", "approved", "rejected"]


class AdvanceTransactionOut(BaseModel):
    id: int
    kind: AdvanceKind
    amount_paise: int
    status: AdvanceStatus
    payment_id: int | None
    reason: str | None
    requested_by: UserRef | None
    approved_by: UserRef | None
    approved_at: datetime | None
    created_at: datetime
    allocations: list[AllocationOut]


class AdvanceOut(BaseModel):
    driver_id: int
    balance_paise: int
    pending_use_paise: int
    adjustments_enabled: bool
    refunds_enabled: bool
    transactions: list[AdvanceTransactionOut]


class AdvanceAdjustmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: int
    items: Annotated[list[AllocationItem], Field(min_length=1, max_length=400)]
    reason: Reason


class AdvanceRefundIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: int
    amount_paise: Paise
    reason: Reason


class AdvanceDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: Annotated[str, Field(max_length=500)] | None = None


class PaymentsSummary(BaseModel):
    awaiting_count: int
    awaiting_paise: int
    awaiting_days_unconfirmed: int
    pending_reversals: int
    pending_advance: int
    requests_today: int
    sent_today: int
    paid_today: int
    unpaid_today: int
