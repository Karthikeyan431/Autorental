"""Validation for settings versions. Defaults follow docs/data-model.md."""

from datetime import datetime, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.settings.models import DEFAULT_WHATSAPP_TEMPLATE

NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
Paise = Annotated[int, Field(strict=True, ge=0)]  # integer paise; floats are refused
IsoWeekday = Annotated[int, Field(strict=True, ge=1, le=7)]  # 1 = Monday
ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class SettingsValues(BaseModel):
    """A complete settings version."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    rent_due_time: time  # no default in the docs: the owner sets it (rule 3)
    due_day_offset: NonNegativeInt = 0  # Q9
    licence_alert_days: NonNegativeInt = 30
    vehicle_alert_days: NonNegativeInt = 30
    permitted_licence_classes: list[ShortText] = Field(default_factory=list)  # N12
    advance_adjustments_enabled: bool = True  # rule 5: the owner can switch it off
    refunds_enabled: bool = False  # Q5
    staff_limit: Annotated[int, Field(strict=True, ge=1)] = 10  # rule 16, N10
    business_name: ShortText | None = None
    business_address: Annotated[str, Field(max_length=500)] | None = None
    business_upi_id: ShortText | None = None  # N5, set in Week 6
    upi_payee_name: ShortText | None = None
    whatsapp_template: Annotated[str, Field(min_length=1, max_length=1000)] = (
        DEFAULT_WHATSAPP_TEMPLATE
    )
    pay_request_time: time = time(8, 0)  # N4
    weekly_pay_day: IsoWeekday = 1  # Monday
    escalation_suggest_after_days: NonNegativeInt = 1  # N9
    weekly_mdr_warning_paise: Paise = 200000  # N3: ₹2,000


class SettingsChanges(BaseModel):
    """The fields to change; everything else is copied from the current version."""

    model_config = ConfigDict(extra="forbid")

    rent_due_time: time | None = None
    due_day_offset: NonNegativeInt | None = None
    licence_alert_days: NonNegativeInt | None = None
    vehicle_alert_days: NonNegativeInt | None = None
    permitted_licence_classes: list[ShortText] | None = None
    advance_adjustments_enabled: bool | None = None
    refunds_enabled: bool | None = None
    staff_limit: Annotated[int, Field(strict=True, ge=1)] | None = None
    business_name: ShortText | None = None
    business_address: Annotated[str, Field(max_length=500)] | None = None
    business_upi_id: ShortText | None = None
    upi_payee_name: ShortText | None = None
    whatsapp_template: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    pay_request_time: time | None = None
    weekly_pay_day: IsoWeekday | None = None
    escalation_suggest_after_days: NonNegativeInt | None = None
    weekly_mdr_warning_paise: Paise | None = None


class SettingsChangeRequest(SettingsChanges):
    """POST /settings: the fields to change, plus an optional reason for the audit log."""

    reason: Annotated[str, Field(max_length=500)] | None = None


class SettingsVersionOut(SettingsValues):
    id: int
    effective_from: datetime
    created_at: datetime
    created_by: int | None
    created_by_name: str | None = None
