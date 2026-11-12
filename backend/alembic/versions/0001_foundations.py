"""Foundations: btree_gist, app_user grants, users (structure only), settings_versions,
audit_logs.

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db_grants import (
    APP_USER_ROLE,
    DEFAULT_PRIVILEGES_DOWN,
    DEFAULT_PRIVILEGES_UP,
    make_insert_only_sql,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_WHATSAPP_TEMPLATE = (
    "Hello {name}, today's auto rent is ₹{amount}. Pay here: {upi_link} "
    "Ref {reference_code}. Thank you, {business_name}"
)


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True)


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # Needed for the agreement exclusion constraints (rule 2, Week 5).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # app_user gets base grants on everything app_owner creates from now on.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_USER_ROLE}")
    for statement in DEFAULT_PRIVILEGES_UP:
        op.execute(statement)

    op.create_table(
        "users",
        _id(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'staff')", name=op.f("ck_users_role_valid")),
        sa.CheckConstraint("failed_logins >= 0", name=op.f("ck_users_failed_logins_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("mobile", name=op.f("uq_users_mobile")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(
        "uq_users_one_owner",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )

    op.create_table(
        "settings_versions",
        _id(),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rent_due_time", sa.Time(), nullable=False),
        sa.Column("due_day_offset", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("licence_alert_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("vehicle_alert_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column(
            "permitted_licence_classes",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "advance_adjustments_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column("refunds_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("staff_limit", sa.Integer(), server_default="10", nullable=False),
        sa.Column("business_name", sa.Text(), nullable=True),
        sa.Column("business_address", sa.Text(), nullable=True),
        sa.Column("business_upi_id", sa.Text(), nullable=True),
        sa.Column("upi_payee_name", sa.Text(), nullable=True),
        sa.Column(
            "whatsapp_template",
            sa.Text(),
            server_default=DEFAULT_WHATSAPP_TEMPLATE,
            nullable=False,
        ),
        sa.Column("pay_request_time", sa.Time(), server_default="08:00", nullable=False),
        sa.Column("weekly_pay_day", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column(
            "escalation_suggest_after_days", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column(
            "weekly_mdr_warning_paise", sa.BigInteger(), server_default="200000", nullable=False
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "due_day_offset >= 0", name=op.f("ck_settings_versions_due_day_offset_non_negative")
        ),
        sa.CheckConstraint(
            "licence_alert_days >= 0",
            name=op.f("ck_settings_versions_licence_alert_days_non_negative"),
        ),
        sa.CheckConstraint(
            "vehicle_alert_days >= 0",
            name=op.f("ck_settings_versions_vehicle_alert_days_non_negative"),
        ),
        sa.CheckConstraint(
            "staff_limit >= 1", name=op.f("ck_settings_versions_staff_limit_positive")
        ),
        sa.CheckConstraint(
            "weekly_pay_day BETWEEN 1 AND 7", name=op.f("ck_settings_versions_weekly_pay_day_iso")
        ),
        sa.CheckConstraint(
            "escalation_suggest_after_days >= 0",
            name=op.f("ck_settings_versions_escalation_suggest_non_negative"),
        ),
        sa.CheckConstraint(
            "weekly_mdr_warning_paise >= 0",
            name=op.f("ck_settings_versions_mdr_warning_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_settings_versions_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings_versions")),
    )
    op.create_index("ix_settings_versions_effective_from", "settings_versions", ["effective_from"])
    op.execute(make_insert_only_sql("settings_versions"))  # rule 3

    op.create_table(
        "audit_logs",
        _id(),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.CHAR(64), nullable=False),
        sa.Column("hash", sa.CHAR(64), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_logs_actor_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.UniqueConstraint("hash", name=op.f("uq_audit_logs_hash")),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.execute(make_insert_only_sql("audit_logs"))  # rule 11


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("settings_versions")
    op.drop_table("users")
    for statement in DEFAULT_PRIVILEGES_DOWN:
        op.execute(statement)
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_USER_ROLE}")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
