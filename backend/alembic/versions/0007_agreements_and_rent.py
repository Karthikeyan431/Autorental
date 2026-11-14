"""Agreements and the daily rent ledger (Week 5), plus the payment tables the day balance reads.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14

* agreements: numbers AG000001, AG000002 ... from agreement_no_seq via next_agreement_no().
  Rule 2 in the database: one active agreement per driver and per vehicle (partial unique
  indexes) and no overlapping periods (`[]` exclusion constraints over active and ended
  agreements, so a new agreement cannot start on the return day, Q1). Once an agreement leaves
  `draft`, its driver, vehicle, start date and daily rate never change (Q10; trigger).
* rent_charges: one row per agreement per calendar day (rule 1), insert-only (rule 11), with its
  own due_at and settings_version_id (rule 3).
* charge_adjustments: signed, non-zero; only approved ones count (Q11).
* payments, payment_allocations, advance_transactions: created now, exactly as
  docs/data-model.md describes, because the day balance reads them (D50). No endpoint writes
  them until Week 6. payments.pay_request_id and payments.statement_line_id get their foreign
  keys in the migrations that create pay_requests (Week 6) and bank_statement_lines (Week 7).
* settings_versions gains max_backdate_days (default 7, N21).
* documents gain the owner type `agreement` and the doc type `signed_agreement`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.db_grants import make_insert_only_sql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOC_TYPES_0006 = (
    "driver_photo",
    "id_front",
    "id_back",
    "licence_front",
    "licence_back",
    "lookup_screenshot",
    "attestation_screenshot",
    "vehicle_paper",
)
_OWNER_TYPES_0006 = ("driver", "kyc_check", "vehicle")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _documents(owner_types: tuple[str, ...], doc_types: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_documents_owner_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_owner_type_valid"), "documents", f"owner_type IN ({_in(owner_types)})"
    )
    op.drop_constraint(op.f("ck_documents_doc_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_doc_type_valid"), "documents", f"doc_type IN ({_in(doc_types)})"
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=f"fk_{table}_{column}_users")


def upgrade() -> None:
    # --- Settings: the backdating limit (N21) ------------------------------------------------
    op.add_column(
        "settings_versions",
        sa.Column("max_backdate_days", sa.Integer(), server_default="7", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_settings_versions_max_backdate_days_non_negative"),
        "settings_versions",
        "max_backdate_days >= 0",
    )

    # --- Agreements -----------------------------------------------------------------------------
    op.execute("CREATE SEQUENCE agreement_no_seq AS bigint START 1")
    op.execute(
        """
        CREATE FUNCTION next_agreement_no() RETURNS text LANGUAGE sql VOLATILE AS $$
          SELECT 'AG' || lpad(n::text, greatest(6, length(n::text)), '0')
          FROM (SELECT nextval('agreement_no_seq') AS n) AS next_value
        $$
        """
    )
    op.create_table(
        "agreements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "agreement_no",
            sa.Text(),
            server_default=sa.text("next_agreement_no()"),
            nullable=False,
        ),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("daily_rent_paise", sa.BigInteger(), nullable=False),
        sa.Column("advance_required_paise", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("terms_version", sa.Text(), nullable=False),
        sa.Column("signed_document_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("activated_by", sa.BigInteger(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.BigInteger(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'ended', 'cancelled')",
            name=op.f("ck_agreements_status_valid"),
        ),
        sa.CheckConstraint("daily_rent_paise > 0", name=op.f("ck_agreements_daily_rent_positive")),
        sa.CheckConstraint(
            "advance_required_paise >= 0", name=op.f("ck_agreements_advance_non_negative")
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name=op.f("ck_agreements_end_after_start"),
        ),
        sa.CheckConstraint(
            "status <> 'ended' OR (end_date IS NOT NULL AND ended_at IS NOT NULL)",
            name=op.f("ck_agreements_ended_has_end_date"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('active', 'ended') OR activated_at IS NOT NULL",
            name=op.f("ck_agreements_activated_has_time"),
        ),
        sa.CheckConstraint(
            "agreement_no ~ '^AG[0-9]{6,}$'", name=op.f("ck_agreements_agreement_no_format")
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_agreements_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], name=op.f("fk_agreements_vehicle_id_vehicles")
        ),
        sa.ForeignKeyConstraint(
            ["signed_document_id"],
            ["documents.id"],
            name=op.f("fk_agreements_signed_document_id_documents"),
        ),
        _user_fk("agreements", "created_by"),
        _user_fk("agreements", "activated_by"),
        _user_fk("agreements", "ended_by"),
        _user_fk("agreements", "cancelled_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agreements")),
        sa.UniqueConstraint("agreement_no", name=op.f("uq_agreements_agreement_no")),
    )
    op.execute("ALTER SEQUENCE agreement_no_seq OWNED BY agreements.agreement_no")
    op.create_index("ix_agreements_driver_id", "agreements", ["driver_id"])
    op.create_index("ix_agreements_vehicle_id", "agreements", ["vehicle_id"])
    op.create_index("ix_agreements_status", "agreements", ["status"])
    # Rule 2: one active agreement per driver and per vehicle; no overlapping periods.
    op.execute(
        "CREATE UNIQUE INDEX one_active_agreement_per_driver ON agreements (driver_id) "
        "WHERE status = 'active'"
    )
    op.execute(
        "CREATE UNIQUE INDEX one_active_agreement_per_vehicle ON agreements (vehicle_id) "
        "WHERE status = 'active'"
    )
    op.execute(
        "ALTER TABLE agreements ADD CONSTRAINT no_driver_overlap EXCLUDE USING gist "
        "(driver_id WITH =, daterange(start_date, end_date, '[]') WITH &&) "
        "WHERE (status IN ('active', 'ended'))"
    )
    op.execute(
        "ALTER TABLE agreements ADD CONSTRAINT no_vehicle_overlap EXCLUDE USING gist "
        "(vehicle_id WITH =, daterange(start_date, end_date, '[]') WITH &&) "
        "WHERE (status IN ('active', 'ended'))"
    )
    # Q10: the rate is fixed per agreement. Once an agreement leaves draft, its number, parties,
    # start date and rate never change, for every role.
    op.execute(
        """
        CREATE FUNCTION agreements_guard_fixed() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.agreement_no IS DISTINCT FROM OLD.agreement_no THEN
            RAISE EXCEPTION 'agreements.agreement_no cannot be changed'
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.status <> 'draft' AND (
               NEW.driver_id IS DISTINCT FROM OLD.driver_id
            OR NEW.vehicle_id IS DISTINCT FROM OLD.vehicle_id
            OR NEW.start_date IS DISTINCT FROM OLD.start_date
            OR NEW.daily_rent_paise IS DISTINCT FROM OLD.daily_rent_paise) THEN
            RAISE EXCEPTION 'an agreement''s driver, auto, start date and rate are fixed'
              USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.status IN ('ended', 'cancelled') AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'an ended or cancelled agreement cannot change status'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER agreements_fixed BEFORE UPDATE ON agreements "
        "FOR EACH ROW EXECUTE FUNCTION agreements_guard_fixed()"
    )

    # --- Rent charges (rule 1, rule 3, rule 11) ---------------------------------------------
    op.create_table(
        "rent_charges",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("agreement_id", sa.BigInteger(), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("rent_date", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settings_version_id", sa.BigInteger(), nullable=False),
        _created_at(),
        sa.CheckConstraint("amount_paise > 0", name=op.f("ck_rent_charges_amount_positive")),
        sa.ForeignKeyConstraint(
            ["agreement_id"],
            ["agreements.id"],
            name=op.f("fk_rent_charges_agreement_id_agreements"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_rent_charges_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["settings_version_id"],
            ["settings_versions.id"],
            name=op.f("fk_rent_charges_settings_version_id_settings_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rent_charges")),
        sa.UniqueConstraint("agreement_id", "rent_date", name="one_charge_per_day"),
    )
    op.execute(make_insert_only_sql("rent_charges"))  # rule 11
    op.create_index("ix_rent_charges_driver_date", "rent_charges", ["driver_id", "rent_date"])
    op.create_index("ix_rent_charges_due_at", "rent_charges", ["due_at"])

    op.create_table(
        "charge_adjustments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("rent_charge_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),  # NULL = the system
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint("amount_paise <> 0", name=op.f("ck_charge_adjustments_amount_non_zero")),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_charge_adjustments_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL AND decided_by IS NULL)",
            name=op.f("ck_charge_adjustments_decision_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["rent_charge_id"],
            ["rent_charges.id"],
            name=op.f("fk_charge_adjustments_rent_charge_id_rent_charges"),
        ),
        _user_fk("charge_adjustments", "requested_by"),
        _user_fk("charge_adjustments", "decided_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charge_adjustments")),
    )
    op.create_index(
        "ix_charge_adjustments_rent_charge_id", "charge_adjustments", ["rent_charge_id"]
    )
    op.execute(
        "CREATE INDEX ix_charge_adjustments_pending ON charge_adjustments (created_at) "
        "WHERE status = 'pending'"
    )

    # --- Payments (structure only until Week 6; D50) -------------------------------------------
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("agreement_id", sa.BigInteger(), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), server_default="rent", nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("pay_request_id", sa.BigInteger(), nullable=True),  # FK in Week 6
        sa.Column("statement_line_id", sa.BigInteger(), nullable=True),  # FK in Week 7
        sa.Column("proof_document_id", sa.BigInteger(), nullable=True),
        sa.Column("recorded_by", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="awaiting_approval", nullable=False),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("receipt_no", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint("amount_paise > 0", name="payment_positive"),
        sa.CheckConstraint("method IN ('upi', 'cash')", name=op.f("ck_payments_method_valid")),
        sa.CheckConstraint(
            "source IN ('pay_request', 'upi_direct', 'cash_office')",
            name=op.f("ck_payments_source_valid"),
        ),
        sa.CheckConstraint(
            "purpose IN ('rent', 'advance_deposit')", name=op.f("ck_payments_purpose_valid")
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_approval', 'approved', 'rejected', 'reversed')",
            name=op.f("ck_payments_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name=op.f("ck_payments_approved_has_approver"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_payments_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id"], ["agreements.id"], name=op.f("fk_payments_agreement_id_agreements")
        ),
        sa.ForeignKeyConstraint(
            ["proof_document_id"],
            ["documents.id"],
            name=op.f("fk_payments_proof_document_id_documents"),
        ),
        _user_fk("payments", "recorded_by"),
        _user_fk("payments", "approved_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("receipt_no", name=op.f("uq_payments_receipt_no")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_payments_idempotency_key")),
    )
    op.create_index("ix_payments_driver_id", "payments", ["driver_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    # The same UPI reference cannot be recorded twice; a statement line backs one payment.
    # Rejected and reversed payments release both, so the money can be re-recorded correctly.
    op.execute(
        "CREATE UNIQUE INDEX unique_payment_reference ON payments (method, reference) "
        "WHERE reference IS NOT NULL AND status NOT IN ('rejected', 'reversed')"
    )
    op.execute(
        "CREATE UNIQUE INDEX one_payment_per_statement_line ON payments (statement_line_id) "
        "WHERE statement_line_id IS NOT NULL AND status NOT IN ('rejected', 'reversed')"
    )

    op.create_table(
        "advance_transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("agreement_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),  # signed
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_by", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint(
            "kind IN ('deposit', 'adjustment', 'refund', 'reversal')",
            name=op.f("ck_advance_transactions_kind_valid"),
        ),
        sa.CheckConstraint(
            "amount_paise <> 0", name=op.f("ck_advance_transactions_amount_non_zero")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_advance_transactions_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name=op.f("ck_advance_transactions_approved_has_approver"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_advance_transactions_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id"],
            ["agreements.id"],
            name=op.f("fk_advance_transactions_agreement_id_agreements"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_advance_transactions_payment_id_payments"),
        ),
        _user_fk("advance_transactions", "requested_by"),
        _user_fk("advance_transactions", "approved_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advance_transactions")),
    )
    op.create_index("ix_advance_transactions_driver_id", "advance_transactions", ["driver_id"])

    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("advance_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("rent_charge_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversed_by", sa.BigInteger(), nullable=True),
        sa.Column("reversal_reason", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint("amount_paise > 0", name="alloc_positive"),
        sa.CheckConstraint(
            "(payment_id IS NULL) <> (advance_transaction_id IS NULL)", name="one_source"
        ),
        sa.CheckConstraint(
            "(reversed_at IS NULL) = (reversal_reason IS NULL)",
            name=op.f("ck_payment_allocations_reversal_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_payment_allocations_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["advance_transaction_id"],
            ["advance_transactions.id"],
            name=op.f("fk_payment_allocations_advance_transaction_id_advance_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["rent_charge_id"],
            ["rent_charges.id"],
            name=op.f("fk_payment_allocations_rent_charge_id_rent_charges"),
        ),
        _user_fk("payment_allocations", "confirmed_by"),
        _user_fk("payment_allocations", "reversed_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_allocations")),
    )
    op.create_index(
        "ix_payment_allocations_rent_charge_id", "payment_allocations", ["rent_charge_id"]
    )
    op.create_index("ix_payment_allocations_payment_id", "payment_allocations", ["payment_id"])

    _documents((*_OWNER_TYPES_0006, "agreement"), (*_DOC_TYPES_0006, "signed_agreement"))


def downgrade() -> None:
    # Signed agreement copies may have insert-only access-log rows, so they are never deleted
    # here: the downgrade stops instead of losing history.
    has_copies = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM documents WHERE owner_type = 'agreement')")
    )
    if has_copies:
        raise RuntimeError("Signed agreement documents exist; downgrade 0007 would orphan them.")
    _documents(_OWNER_TYPES_0006, _DOC_TYPES_0006)
    op.drop_table("payment_allocations")
    op.drop_table("advance_transactions")
    op.drop_table("payments")
    op.drop_table("charge_adjustments")
    op.drop_table("rent_charges")
    op.drop_table("agreements")  # drops its trigger, indexes and the owned agreement_no_seq
    op.execute("DROP FUNCTION agreements_guard_fixed()")
    op.execute("DROP FUNCTION next_agreement_no()")
    op.drop_constraint(
        op.f("ck_settings_versions_max_backdate_days_non_negative"),
        "settings_versions",
        type_="check",
    )
    op.drop_column("settings_versions", "max_backdate_days")
