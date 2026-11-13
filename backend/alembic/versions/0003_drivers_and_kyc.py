"""Drivers and KYC: drivers (code sequence, immutable created_by), manager history,
restrictions, consents, documents and their access log, KYC attempts, events and details,
alerts, and settings_versions.accepted_id_types (N12).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13

Checklist for every migration (docs/data-model.md):
* New tables get app_user's base grants automatically (ALTER DEFAULT PRIVILEGES in 0001).
* An insert-only table must be in app.core.db_grants.INSERT_ONLY_TABLES and must run
  op.execute(make_insert_only_sql("<table>")) right after it is created.
* downgrade() must undo everything upgrade() does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db_grants import make_insert_only_sql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name=op.f("ck_alerts_severity_valid")
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL) OR (resolved_at >= created_at)",
            name=op.f("ck_alerts_resolved_after_created"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_alerts_resolved_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_alerts_dedupe_key")),
    )
    op.create_index("ix_alerts_entity", "alerts", ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_alerts_kind_open", "alerts", ["kind", "resolved_at"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("retention_until", sa.Date(), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "doc_type IN ('driver_photo', 'id_front', 'id_back', 'licence_front', 'licence_back')",
            name=op.f("ck_documents_doc_type_valid"),
        ),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'application/pdf')",
            name=op.f("ck_documents_mime_type_valid"),
        ),
        sa.CheckConstraint(
            "owner_type IN ('driver', 'kyc_check')", name=op.f("ck_documents_owner_type_valid")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256_hex")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_documents_size_non_negative")),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_documents_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
    )
    op.create_index("ix_documents_owner", "documents", ["owner_type", "owner_id"], unique=False)
    # Driver codes D0001, D0002 ... (more digits after D9999). The sequence is owned by
    # drivers.code, so TRUNCATE ... RESTART IDENTITY resets it too.
    op.execute("CREATE SEQUENCE driver_code_seq AS bigint START 1")
    op.execute(
        """
        CREATE FUNCTION next_driver_code() RETURNS text LANGUAGE sql VOLATILE AS $$
          SELECT 'D' || lpad(n::text, greatest(4, length(n::text)), '0')
          FROM (SELECT nextval('driver_code_seq') AS n) AS next_value
        $$
        """
    )
    op.create_table(
        "drivers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.Text(), server_default=sa.text("next_driver_code()"), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("alt_mobile", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("emergency_name", sa.Text(), nullable=True),
        sa.Column("emergency_mobile", sa.Text(), nullable=True),
        sa.Column("photo_document_id", sa.BigInteger(), nullable=True),
        sa.Column("account_status", sa.Text(), server_default="active", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("payment_rhythm", sa.Text(), server_default="daily", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("managed_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_status IN ('active', 'suspended', 'inactive')",
            name=op.f("ck_drivers_account_status_valid"),
        ),
        sa.CheckConstraint(
            "payment_rhythm IN ('daily', 'weekly')", name=op.f("ck_drivers_payment_rhythm_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_drivers_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["managed_by"], ["users.id"], name=op.f("fk_drivers_managed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["photo_document_id"],
            ["documents.id"],
            name="fk_drivers_photo_document",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drivers")),
        sa.UniqueConstraint("code", name=op.f("uq_drivers_code")),
        sa.UniqueConstraint("mobile", name=op.f("uq_drivers_mobile")),
    )
    op.create_index("ix_drivers_created_by", "drivers", ["created_by"], unique=False)
    op.create_index("ix_drivers_managed_by", "drivers", ["managed_by"], unique=False)
    op.execute("ALTER SEQUENCE driver_code_seq OWNED BY drivers.code")
    # Rule 14: created_by never changes; nor does the public code. Enforced for every role.
    op.execute(
        """
        CREATE FUNCTION drivers_guard_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
            RAISE EXCEPTION 'drivers.created_by cannot be changed'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.code IS DISTINCT FROM OLD.code THEN
            RAISE EXCEPTION 'drivers.code cannot be changed'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER drivers_immutable BEFORE UPDATE ON drivers "
        "FOR EACH ROW EXECUTE FUNCTION drivers_guard_immutable()"
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("notice_version", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("captured_by", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by", sa.BigInteger(), nullable=True),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('in_person_signed', 'in_person_checkbox')",
            name=op.f("ck_consents_method_valid"),
        ),
        sa.CheckConstraint(
            "purpose IN ('kyc', 'aadhaar_qr')", name=op.f("ck_consents_purpose_valid")
        ),
        sa.CheckConstraint(
            "(withdrawn_at IS NULL) = (withdrawn_by IS NULL)",
            name=op.f("ck_consents_withdrawn_fields_together"),
        ),
        sa.ForeignKeyConstraint(
            ["captured_by"], ["users.id"], name=op.f("fk_consents_captured_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_consents_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["withdrawn_by"], ["users.id"], name=op.f("fk_consents_withdrawn_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_driver_id"), "consents", ["driver_id"], unique=False)
    op.create_table(
        "document_access_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('view', 'download')", name=op.f("ck_document_access_log_purpose_valid")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_access_log_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_document_access_log_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_access_log")),
    )
    op.create_index(
        op.f("ix_document_access_log_document_id"),
        "document_access_log",
        ["document_id"],
        unique=False,
    )
    op.execute(make_insert_only_sql("document_access_log"))
    op.create_table(
        "driver_manager_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("from_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_by", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "to_at IS NULL OR to_at >= from_at", name=op.f("ck_driver_manager_history_period_valid")
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"], ["users.id"], name=op.f("fk_driver_manager_history_changed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_driver_manager_history_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["users.id"], name=op.f("fk_driver_manager_history_staff_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_manager_history")),
    )
    op.create_index(
        op.f("ix_driver_manager_history_driver_id"),
        "driver_manager_history",
        ["driver_id"],
        unique=False,
    )
    op.create_index(
        "uq_driver_manager_history_open",
        "driver_manager_history",
        ["driver_id"],
        unique=True,
        postgresql_where=sa.text("to_at IS NULL"),
    )
    op.create_table(
        "driver_restrictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("placed_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("lifted_by", sa.BigInteger(), nullable=True),
        sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lift_reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(lifted_at IS NULL) = (lifted_by IS NULL)",
            name=op.f("ck_driver_restrictions_lifted_fields_together"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_driver_restrictions_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["lifted_by"], ["users.id"], name=op.f("fk_driver_restrictions_lifted_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["placed_by"], ["users.id"], name=op.f("fk_driver_restrictions_placed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_restrictions")),
    )
    op.create_index(
        op.f("ix_driver_restrictions_driver_id"), "driver_restrictions", ["driver_id"], unique=False
    )
    op.create_table(
        "kyc_checks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("check_type", sa.Text(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("review_checklist", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("reopened_from_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "check_type IN ('identity', 'licence')", name=op.f("ck_kyc_checks_check_type_valid")
        ),
        sa.CheckConstraint(
            "method IN ('uidai_qr', 'uidai_app_attested', 'parivahan_lookup', 'manual', 'demo')",
            name=op.f("ck_kyc_checks_method_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'under_review', 'approved', 'rejected', "
            "'resubmission_required', 'expired')",
            name=op.f("ck_kyc_checks_status_valid"),
        ),
        sa.CheckConstraint("attempt_no >= 1", name=op.f("ck_kyc_checks_attempt_no_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_kyc_checks_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_kyc_checks_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["reopened_from_id"],
            ["kyc_checks.id"],
            name=op.f("fk_kyc_checks_reopened_from_id_kyc_checks"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_kyc_checks_reviewed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_checks")),
        sa.UniqueConstraint("driver_id", "check_type", "attempt_no", name="uq_kyc_checks_attempt"),
    )
    op.create_index(op.f("ix_kyc_checks_driver_id"), "kyc_checks", ["driver_id"], unique=False)
    op.create_index(
        "uq_kyc_checks_current",
        "kyc_checks",
        ["driver_id", "check_type"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "identity_details",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kyc_check_id", sa.BigInteger(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("id_last4", sa.Text(), nullable=False),
        sa.Column("name_on_document", sa.Text(), nullable=True),
        sa.Column("dob_or_yob", sa.Text(), nullable=True),
        sa.Column("gender", sa.Text(), nullable=True),
        sa.Column("qr_signature_valid", sa.Boolean(), nullable=True),
        sa.Column("photo_match_confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "document_type IN ('masked_aadhaar', 'voter_id', 'passport')",
            name=op.f("ck_identity_details_document_type_valid"),
        ),
        sa.CheckConstraint(
            "id_last4 ~ '^[0-9]{4}$'", name=op.f("ck_identity_details_id_last4_four_digits")
        ),
        sa.ForeignKeyConstraint(
            ["kyc_check_id"],
            ["kyc_checks.id"],
            name=op.f("fk_identity_details_kyc_check_id_kyc_checks"),
        ),
        sa.ForeignKeyConstraint(
            ["photo_match_confirmed_by"],
            ["users.id"],
            name=op.f("fk_identity_details_photo_match_confirmed_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_details")),
        sa.UniqueConstraint("kyc_check_id", name=op.f("uq_identity_details_kyc_check_id")),
    )
    op.create_table(
        "kyc_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kyc_check_id", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_kyc_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["kyc_check_id"], ["kyc_checks.id"], name=op.f("fk_kyc_events_kyc_check_id_kyc_checks")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_events")),
    )
    op.create_index(
        op.f("ix_kyc_events_kyc_check_id"), "kyc_events", ["kyc_check_id"], unique=False
    )
    op.execute(make_insert_only_sql("kyc_events"))
    op.create_table(
        "licence_details",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("kyc_check_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("licence_number", sa.Text(), nullable=False),
        sa.Column("licence_number_hash", sa.Text(), nullable=False),
        sa.Column("licence_number_last4", sa.Text(), nullable=False),
        sa.Column("name_on_licence", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("valid_until_non_transport", sa.Date(), nullable=True),
        sa.Column("valid_until_transport", sa.Date(), nullable=True),
        sa.Column("vehicle_classes", sa.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("issuing_authority", sa.Text(), nullable=True),
        sa.Column("lookup_status_text", sa.Text(), nullable=True),
        sa.Column("looked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lookup_screenshot_document_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "licence_number_last4 ~ '^[A-Z0-9]{1,4}$'", name=op.f("ck_licence_details_last4_valid")
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_licence_details_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["kyc_check_id"],
            ["kyc_checks.id"],
            name=op.f("fk_licence_details_kyc_check_id_kyc_checks"),
        ),
        sa.ForeignKeyConstraint(
            ["lookup_screenshot_document_id"],
            ["documents.id"],
            name=op.f("fk_licence_details_lookup_screenshot_document_id_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_licence_details")),
        sa.UniqueConstraint("kyc_check_id", name=op.f("uq_licence_details_kyc_check_id")),
    )
    op.create_index(
        op.f("ix_licence_details_driver_id"), "licence_details", ["driver_id"], unique=False
    )
    op.create_index(
        op.f("ix_licence_details_licence_number_hash"),
        "licence_details",
        ["licence_number_hash"],
        unique=False,
    )
    # One licence number belongs to one driver; that driver's later attempts may repeat it
    # (an owner reopen copies the details). btree_gist was installed in 0001.
    op.execute(
        "ALTER TABLE licence_details ADD CONSTRAINT ex_licence_details_one_driver_per_licence "
        "EXCLUDE USING gist (licence_number_hash WITH =, driver_id WITH <>)"
    )
    op.add_column(
        "settings_versions",
        sa.Column(
            "accepted_id_types",
            sa.ARRAY(sa.Text()),
            server_default="{masked_aadhaar}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("settings_versions", "accepted_id_types")
    op.drop_index(op.f("ix_licence_details_licence_number_hash"), table_name="licence_details")
    op.drop_index(op.f("ix_licence_details_driver_id"), table_name="licence_details")
    op.drop_table("licence_details")
    op.drop_index(op.f("ix_kyc_events_kyc_check_id"), table_name="kyc_events")
    op.drop_table("kyc_events")
    op.drop_table("identity_details")
    op.drop_index(
        "uq_kyc_checks_current", table_name="kyc_checks", postgresql_where=sa.text("is_current")
    )
    op.drop_index(op.f("ix_kyc_checks_driver_id"), table_name="kyc_checks")
    op.drop_table("kyc_checks")
    op.drop_index(op.f("ix_driver_restrictions_driver_id"), table_name="driver_restrictions")
    op.drop_table("driver_restrictions")
    op.drop_index(
        "uq_driver_manager_history_open",
        table_name="driver_manager_history",
        postgresql_where=sa.text("to_at IS NULL"),
    )
    op.drop_index(op.f("ix_driver_manager_history_driver_id"), table_name="driver_manager_history")
    op.drop_table("driver_manager_history")
    op.drop_index(op.f("ix_document_access_log_document_id"), table_name="document_access_log")
    op.drop_table("document_access_log")
    op.drop_index(op.f("ix_consents_driver_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index("ix_drivers_managed_by", table_name="drivers")
    op.drop_index("ix_drivers_created_by", table_name="drivers")
    op.drop_table("drivers")  # drops its trigger and the owned driver_code_seq
    op.execute("DROP FUNCTION drivers_guard_immutable()")
    op.execute("DROP FUNCTION next_driver_code()")
    op.drop_index("ix_documents_owner", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_alerts_kind_open", table_name="alerts")
    op.drop_index("ix_alerts_entity", table_name="alerts")
    op.drop_table("alerts")
