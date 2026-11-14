"""Pay request responses (docs/api.md "Pay requests")."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.drivers.schemas import UserRef

PayRequestStatus = Literal["open", "paid", "superseded", "cancelled"]


class DriverRef(BaseModel):
    id: int
    code: str
    full_name: str


class PayRequestOut(BaseModel):
    id: int
    driver: DriverRef
    managed_by: UserRef
    agreement_id: int
    period_start: date
    period_end: date
    amount_paise: int
    reference_code: str
    status: PayRequestStatus
    send_count: int
    sent_at: datetime | None
    sent_by: UserRef | None
    upi_link: str
    whatsapp_url: str
    # N3: merchant UPI payments above the setting (₹2,000) carry a 0.4% charge.
    mdr_warning: bool
    # N8: recorded payments linked to this request that still await the owner.
    awaiting_approval_paise: int
    created_at: datetime


class GenerationOut(BaseModel):
    created: int
    superseded: int
    unchanged: int
