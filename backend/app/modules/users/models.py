"""Users (the owner and up to `staff_limit` staff) and their granted permissions."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, TimestampMixin
from app.core.permissions import GRANTABLE

USER_ROLES = ("owner", "staff")

# The database also refuses owner-only codes (docs/data-model.md: "service check plus a CHECK").
GRANTABLE_CODES_SQL = ", ".join(f"'{code.value}'" for code in sorted(GRANTABLE))


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'staff')", name="role_valid"),
        CheckConstraint("failed_logins >= 0", name="failed_logins_non_negative"),
        CheckConstraint(
            "role = 'owner' OR (totp_secret IS NULL AND totp_pending_secret IS NULL)",
            name="totp_owner_only",
        ),
        # Exactly one owner account.
        Index("uq_users_one_owner", "role", unique=True, postgresql_where="role = 'owner'"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mobile: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    totp_secret: Mapped[str | None] = mapped_column(Text)  # encrypted value (owner only)
    totp_pending_secret: Mapped[str | None] = mapped_column(Text)  # encrypted, until confirmed
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)  # refuses a reused code
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPermission(CreatedAtMixin, Base):
    """A permission granted to a staff member. The owner has every permission implicitly."""

    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_code", name="uq_user_permissions_user_code"),
        CheckConstraint(f"permission_code IN ({GRANTABLE_CODES_SQL})", name="code_grantable"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
