"""Ledger, overdue and adjustment shapes. Money is integer paise (hard constraint 4)."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.identifiers import NoAadhaarStr
from app.modules.drivers.schemas import UserRef

Reason = Annotated[NoAadhaarStr, Field(min_length=1, max_length=500)]
DayStatus = Literal["paid", "part_paid", "unpaid", "waived"]


class AdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Signed paise: negative waives (part of) the day; never zero.
    amount_paise: Annotated[int, Field(strict=True, ge=-10_000_000, le=10_000_000)]
    reason: Reason

    @field_validator("amount_paise")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("The adjustment cannot be zero.")
        return value


class AdjustmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: Reason | None = None


class AdjustmentOut(BaseModel):
    id: int
    rent_charge_id: int
    rent_date: date
    driver_id: int
    amount_paise: int
    reason: str
    status: str
    requested_by: UserRef | None
    created_at: datetime
    decided_by: UserRef | None
    decided_at: datetime | None
    decision_reason: str | None


class LedgerRow(BaseModel):
    charge_id: int
    agreement_id: int
    agreement_no: str
    rent_date: date
    due_at: datetime
    charge_paise: int
    adjustments_paise: int  # approved only (Q11)
    pending_adjustments_paise: int  # shown, never counted
    allocated_paise: int  # approved payments only (rule 13)
    awaiting_approval_paise: int  # shown, never subtracted (N8)
    balance_paise: int
    status: DayStatus
    is_overdue: bool
    pending_adjustment_ids: list[int] = []


class LedgerTotals(BaseModel):
    charge_paise: int
    adjustments_paise: int
    allocated_paise: int
    balance_paise: int


class LedgerOut(BaseModel):
    driver_id: int
    as_of: datetime
    rows: list[LedgerRow]
    totals: LedgerTotals  # of the rows shown
    outstanding_paise: int  # every day up to now, whatever the filter
    overdue_paise: int


class OverdueRow(BaseModel):
    driver_id: int
    driver_code: str
    driver_name: str
    managed_by: UserRef
    overdue_paise: int
    outstanding_paise: int
    awaiting_approval_paise: int
    oldest_overdue_date: date
    days_overdue: int


class RentSummary(BaseModel):
    """Owner dashboard cards (Week 5). `scope` is `all` for the owner and staff with
    `reports.all`, otherwise `own` (the drivers the staff member manages; N1)."""

    scope: Literal["all", "own"]
    as_of: datetime
    rent_expected_today_paise: int
    active_agreements: int
    overdue_drivers: int
    overdue_paise: int
    adjustments_pending: int


class AccrualOut(BaseModel):
    charges_created: int
    agreements: int
