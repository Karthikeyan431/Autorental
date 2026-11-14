"""Business settings, versioned (rule 3). Rows are never updated: each change inserts a new
version, and "current" is the latest version whose effective_from has passed."""

from datetime import datetime, time

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin

DEFAULT_WHATSAPP_TEMPLATE = (
    "Hello {name}, today's auto rent is ₹{amount}. Pay here: {upi_link} "
    "Ref {reference_code}. Thank you, {business_name}"
)


class SettingsVersion(CreatedAtMixin, Base):
    __tablename__ = "settings_versions"
    __table_args__ = (
        CheckConstraint("due_day_offset >= 0", name="due_day_offset_non_negative"),
        CheckConstraint("licence_alert_days >= 0", name="licence_alert_days_non_negative"),
        CheckConstraint("vehicle_alert_days >= 0", name="vehicle_alert_days_non_negative"),
        CheckConstraint("staff_limit >= 1", name="staff_limit_positive"),
        CheckConstraint("weekly_pay_day BETWEEN 1 AND 7", name="weekly_pay_day_iso"),
        CheckConstraint(
            "escalation_suggest_after_days >= 0", name="escalation_suggest_non_negative"
        ),
        CheckConstraint("weekly_mdr_warning_paise >= 0", name="mdr_warning_non_negative"),
        CheckConstraint("reveal_limit_per_hour >= 1", name="reveal_limit_positive"),
        CheckConstraint("max_backdate_days >= 0", name="max_backdate_days_non_negative"),
        Index("ix_settings_versions_effective_from", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rent_due_time: Mapped[time] = mapped_column(Time, nullable=False)
    due_day_offset: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    licence_alert_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    vehicle_alert_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    permitted_licence_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    # N12: identity documents accepted for manual review (Week 3). Default: masked Aadhaar only.
    accepted_id_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{masked_aadhaar}"
    )
    advance_adjustments_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    refunds_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    staff_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    business_name: Mapped[str | None] = mapped_column(Text)
    business_address: Mapped[str | None] = mapped_column(Text)
    business_upi_id: Mapped[str | None] = mapped_column(Text)
    upi_payee_name: Mapped[str | None] = mapped_column(Text)
    whatsapp_template: Mapped[str] = mapped_column(Text, nullable=False)
    pay_request_time: Mapped[time] = mapped_column(Time, nullable=False, server_default="08:00")
    weekly_pay_day: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )  # ISO weekday, 1 = Monday
    escalation_suggest_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    reveal_limit_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    # N21: how many days before today an agreement may start (Week 5).
    max_backdate_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    weekly_mdr_warning_paise: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="200000"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )  # NULL = the system seed
