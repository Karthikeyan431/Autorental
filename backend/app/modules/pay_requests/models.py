"""Pay requests: the free replacement for Autopay (docs/rent-and-payments.md §2; rule 18).

One request per driver per period, with amount = outstanding up to and including the period.
At most one request per driver is `open` (D57); a new period supersedes the old one.
"""

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

PAY_REQUEST_STATUSES = ("open", "paid", "superseded", "cancelled")


class PayRequest(TimestampMixin, Base):
    __tablename__ = "pay_requests"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drivers.id"), nullable=False)
    agreement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agreements.id"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_code: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_charge_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    sent_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
