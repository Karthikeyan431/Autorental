"""The daily rent ledger (docs/rent-and-payments.md §1).

* `rent_charges`: one row per agreement per calendar day (rule 1), insert-only (rule 11). Each
  row keeps the `due_at` and `settings_version_id` in force when it was created (rule 3).
* `charge_adjustments`: signed (negative = waiver). Only approved ones count (Q11).

Outstanding, overdue and balances are never stored: see app.modules.rent.ledger.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, TimestampMixin

ADJUSTMENT_STATUSES = ("pending", "approved", "rejected")


class RentCharge(CreatedAtMixin, Base):
    __tablename__ = "rent_charges"
    __table_args__ = (
        UniqueConstraint("agreement_id", "rent_date", name="one_charge_per_day"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    agreement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agreements.id"), nullable=False
    )
    driver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drivers.id"), nullable=False)
    rent_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settings_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("settings_versions.id"), nullable=False
    )


class ChargeAdjustment(TimestampMixin, Base):
    __tablename__ = "charge_adjustments"
    __table_args__ = (
        CheckConstraint("amount_paise <> 0", name="amount_non_zero"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    rent_charge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rent_charges.id"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
