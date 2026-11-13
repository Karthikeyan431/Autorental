"""Business alerts (docs/data-model.md). Week 3 raises licence-expiry alerts (Q23); per-user
notifications and the bell arrive in Week 7.

`dedupe_key` makes the jobs idempotent: the same alert is never raised twice.
Messages hold codes and dates only, never names, mobiles or document numbers.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

SEVERITIES = ("info", "warning", "critical")


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity_valid"),
        CheckConstraint(
            "(resolved_at IS NULL) OR (resolved_at >= created_at)", name="resolved_after_created"
        ),
        Index("ix_alerts_entity", "entity_type", "entity_id"),
        Index("ix_alerts_kind_open", "kind", "resolved_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
