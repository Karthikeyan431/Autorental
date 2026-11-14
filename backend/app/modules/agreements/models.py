"""Agreements (docs/data-model.md "Agreements and rent"; Week 5).

Rule 2 is enforced by the database (migration 0007): one active agreement per driver and per
vehicle (partial unique indexes) and no overlapping `[]` date ranges among active and ended
agreements, so an auto cannot go to a new driver on its return day (Q1). Once an agreement
leaves `draft`, its driver, auto, start date and rate never change (Q10; trigger).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

AGREEMENT_STATUSES = ("draft", "active", "ended", "cancelled")
# Q13: we write no legal terms. The printed agreement uses this placeholder template.
TERMS_VERSION = "placeholder-v1"


class Agreement(TimestampMixin, Base):
    __tablename__ = "agreements"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'ended', 'cancelled')", name="status_valid"),
        CheckConstraint("daily_rent_paise > 0", name="daily_rent_positive"),
        CheckConstraint("advance_required_paise >= 0", name="advance_non_negative"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # AG000001, AG000002 ... from agreement_no_seq (migration 0007).
    agreement_no: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, server_default=text("next_agreement_no()")
    )
    driver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    daily_rent_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    advance_required_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    terms_version: Mapped[str] = mapped_column(Text, nullable=False)
    signed_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id"))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    activated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
