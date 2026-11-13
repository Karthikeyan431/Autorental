"""Sign-in state: refresh-token sessions, owner recovery codes, and the per-IP throttle."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin

REVOKE_REASONS = (
    "rotated",
    "logout",
    "reuse_detected",
    "deactivated",
    "password_reset",
    "password_changed",
)


class AuthSession(CreatedAtMixin, Base):
    """One row per refresh token. Rotation adds a row to the same family and marks the old row
    `rotated`; presenting a rotated token again revokes the whole family."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "revoked_reason IS NULL OR revoked_reason IN "
            "('rotated', 'logout', 'reuse_detected', 'deactivated', 'password_reset', "
            "'password_changed')",
            name="revoked_reason_valid",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)", name="revoked_fields_together"
        ),
        Index("ix_sessions_family_id", "family_id"),
        Index("ix_sessions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    family_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    replaced_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sessions.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)


class RecoveryCode(CreatedAtMixin, Base):
    """Owner recovery codes, stored as SHA-256 hashes (each code has about 50 random bits)."""

    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(CreatedAtMixin, Base):
    """Sign-in attempts by IP address, for the throttle. No account identifier is stored."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_ip_attempted_at", "ip", "attempted_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ip: Mapped[str | None] = mapped_column(INET)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
