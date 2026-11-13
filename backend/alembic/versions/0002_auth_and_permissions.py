"""Sign-in and permissions: users TOTP columns, user_permissions, sessions, recovery_codes,
login_attempts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of app.core.permissions.GRANTABLE at this revision. Owner-only codes are refused
# by the database as well as by the service. Changing the list needs a new migration.
GRANTABLE_CODES_SQL = (
    "'adjustments.request', 'agreements.manage', 'drivers.create', 'drivers.edit_any', "
    "'drivers.edit_own', 'drivers.restrict', 'escalations.work', 'kyc.decide', "
    "'payments.record', 'payrequests.send', 'reports.all', 'statements.upload', "
    "'vehicles.manage'"
)


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True)


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_pending_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_users_totp_owner_only"),
        "users",
        "role = 'owner' OR (totp_secret IS NULL AND totp_pending_secret IS NULL)",
    )

    op.create_table(
        "user_permissions",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _created_at(),
        sa.CheckConstraint(
            f"permission_code IN ({GRANTABLE_CODES_SQL})",
            name=op.f("ck_user_permissions_code_grantable"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_permissions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["users.id"], name=op.f("fk_user_permissions_granted_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_permissions")),
        sa.UniqueConstraint("user_id", "permission_code", name="uq_user_permissions_user_code"),
    )
    op.create_index("ix_user_permissions_user_id", "user_permissions", ["user_id"])

    op.create_table(
        "sessions",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("family_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("replaced_by_id", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "revoked_reason IS NULL OR revoked_reason IN "
            "('rotated', 'logout', 'reuse_detected', 'deactivated', 'password_reset', "
            "'password_changed')",
            name=op.f("ck_sessions_revoked_reason_valid"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)",
            name=op.f("ck_sessions_revoked_fields_together"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"], ["sessions.id"], name=op.f("fk_sessions_replaced_by_id_sessions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_sessions_refresh_token_hash")),
    )
    op.create_index("ix_sessions_family_id", "sessions", ["family_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "recovery_codes",
        _id(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_recovery_codes_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_recovery_codes_code_hash")),
    )
    op.create_index("ix_recovery_codes_user_id", "recovery_codes", ["user_id"])

    op.create_table(
        "login_attempts",
        _id(),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index("ix_login_attempts_ip_attempted_at", "login_attempts", ["ip", "attempted_at"])


def downgrade() -> None:
    op.drop_table("login_attempts")
    op.drop_table("recovery_codes")
    op.drop_table("sessions")
    op.drop_table("user_permissions")
    op.drop_constraint(op.f("ck_users_totp_owner_only"), "users", type_="check")
    for column in (
        "deactivated_at",
        "password_changed_at",
        "totp_last_step",
        "totp_confirmed_at",
        "totp_pending_secret",
    ):
        op.drop_column("users", column)
