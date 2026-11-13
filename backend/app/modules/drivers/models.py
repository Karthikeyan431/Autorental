"""Drivers, who manages them, restrictions and consents (rule 14, docs/data-model.md).

`created_by` and `code` never change: the service never writes them after insert, and the
trigger `drivers_guard_immutable` (migration 0003) refuses any UPDATE that tries.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

ACCOUNT_STATUSES = ("active", "suspended", "inactive")
PAYMENT_RHYTHMS = ("daily", "weekly")
CONSENT_PURPOSES = ("kyc", "aadhaar_qr")
CONSENT_METHODS = ("in_person_signed", "in_person_checkbox")


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"
    __table_args__ = (
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'inactive')", name="account_status_valid"
        ),
        CheckConstraint("payment_rhythm IN ('daily', 'weekly')", name="payment_rhythm_valid"),
        Index("ix_drivers_managed_by", "managed_by"),
        Index("ix_drivers_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # D0001, D0002 ... from driver_code_seq (migration 0003).
    code: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, server_default=text("next_driver_code()")
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    mobile: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # +91XXXXXXXXXX
    alt_mobile: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    emergency_name: Mapped[str | None] = mapped_column(Text)
    emergency_mobile: Mapped[str | None] = mapped_column(Text)
    photo_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", use_alter=True, name="fk_drivers_photo_document")
    )
    account_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    status_reason: Mapped[str | None] = mapped_column(Text)
    payment_rhythm: Mapped[str] = mapped_column(Text, nullable=False, server_default="daily")
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    managed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DriverManagerHistory(TimestampMixin, Base):
    """Who managed the driver, and when. Exactly one open row (to_at IS NULL) per driver."""

    __tablename__ = "driver_manager_history"
    __table_args__ = (
        Index(
            "uq_driver_manager_history_open",
            "driver_id",
            unique=True,
            postgresql_where=text("to_at IS NULL"),
        ),
        CheckConstraint("to_at IS NULL OR to_at >= from_at", name="period_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("drivers.id"), nullable=False, index=True
    )
    staff_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    to_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class DriverRestriction(TimestampMixin, Base):
    """A block placed by the owner (Q26). Only blocking, unlifted rows affect eligibility."""

    __tablename__ = "driver_restrictions"
    __table_args__ = (
        CheckConstraint("(lifted_at IS NULL) = (lifted_by IS NULL)", name="lifted_fields_together"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("drivers.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    placed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lifted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lift_reason: Mapped[str | None] = mapped_column(Text)


class Consent(TimestampMixin, Base):
    """Recorded before any KYC step (UIDAI: no offline verification without explicit consent)."""

    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint("purpose IN ('kyc', 'aadhaar_qr')", name="purpose_valid"),
        CheckConstraint(
            "method IN ('in_person_signed', 'in_person_checkbox')", name="method_valid"
        ),
        CheckConstraint(
            "(withdrawn_at IS NULL) = (withdrawn_by IS NULL)", name="withdrawn_fields_together"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("drivers.id"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    notice_version: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    captured_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
