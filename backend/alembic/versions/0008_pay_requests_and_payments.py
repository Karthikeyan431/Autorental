"""Pay requests, payment approval, receipts, reversals and advance (Week 6).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14

* pay_requests: one per driver per period (rule 18). At most one `open` request per driver
  (D57, C1); a period never gets a second live request (superseded ones are kept).
  Reference codes are letters and digits only: `R` + 4-digit driver number + MMDD.
* payments: the foreign key on pay_request_id (D50), who rejected or reversed it and when, and
  when its receipt was cancelled. An approved payment always has a receipt number (rule 13).
* reversal_requests: staff ask, the owner decides (Q4). One pending request per payment.
* receipt_counters: one row per financial year, row-locked while a number is issued, so
  numbers have no gaps (`RCPT/2026-27/000123`).
* advance_transactions: the sign follows the kind, and a deferred constraint trigger refuses
  any commit that leaves a driver's approved advance balance below 0 (rule 5).
* documents gain the owner type `payment` and the doc type `payment_proof`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOC_TYPES_0007 = (
    "driver_photo",
    "id_front",
    "id_back",
    "licence_front",
    "licence_back",
    "lookup_screenshot",
    "attestation_screenshot",
    "vehicle_paper",
    "signed_agreement",
)
_OWNER_TYPES_0007 = ("driver", "kyc_check", "vehicle", "agreement")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _documents(owner_types: tuple[str, ...], doc_types: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_documents_owner_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_owner_type_valid"), "documents", f"owner_type IN ({_in(owner_types)})"
    )
    op.drop_constraint(op.f("ck_documents_doc_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_doc_type_valid"), "documents", f"doc_type IN ({_in(doc_types)})"
    )


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=f"fk_{table}_{column}_users")


def upgrade() -> None:
    # --- Pay requests (rule 18) ------------------------------------------------------------------
    op.create_table(
        "pay_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("driver_id", sa.BigInteger(), nullable=False),
        sa.Column("agreement_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("reference_code", sa.Text(), nullable=False),
        sa.Column(
            "suggested_charge_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("sent_by", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_count", sa.Integer(), server_default="0", nullable=False),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('open', 'paid', 'superseded', 'cancelled')",
            name=op.f("ck_pay_requests_status_valid"),
        ),
        sa.CheckConstraint("amount_paise > 0", name=op.f("ck_pay_requests_amount_positive")),
        sa.CheckConstraint("period_end >= period_start", name=op.f("ck_pay_requests_period_valid")),
        sa.CheckConstraint(
            "reference_code ~ '^R[0-9]{8,}$'", name=op.f("ck_pay_requests_reference_format")
        ),
        sa.CheckConstraint("send_count >= 0", name=op.f("ck_pay_requests_send_count_valid")),
        sa.CheckConstraint(
            "(send_count = 0) = (sent_at IS NULL AND sent_by IS NULL)",
            name=op.f("ck_pay_requests_sent_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_pay_requests_driver_id_drivers")
        ),
        sa.ForeignKeyConstraint(
            ["agreement_id"],
            ["agreements.id"],
            name=op.f("fk_pay_requests_agreement_id_agreements"),
        ),
        _user_fk("pay_requests", "sent_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pay_requests")),
        sa.UniqueConstraint(
            "reference_code", "period_start", name=op.f("uq_pay_requests_reference_period")
        ),
    )
    op.create_index("ix_pay_requests_period_start", "pay_requests", ["period_start"])
    # D57 (C1): a single open request per driver; and a period never gets a second live one.
    op.execute(
        "CREATE UNIQUE INDEX one_open_pay_request_per_driver ON pay_requests (driver_id) "
        "WHERE status = 'open'"
    )
    op.execute(
        "CREATE UNIQUE INDEX one_pay_request_per_driver_period ON pay_requests "
        "(driver_id, period_start) WHERE status <> 'superseded'"
    )

    # --- Payments: Week 6 columns and checks -----------------------------------------------------
    op.add_column("payments", sa.Column("rejected_by", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("reversed_by", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "payments", sa.Column("receipt_cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_payments_pay_request_id_pay_requests",
        "payments",
        "pay_requests",
        ["pay_request_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_payments_rejected_by_users", "payments", "users", ["rejected_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_payments_reversed_by_users", "payments", "users", ["reversed_by"], ["id"]
    )
    op.create_check_constraint(
        op.f("ck_payments_approved_has_receipt"),
        "payments",
        "status NOT IN ('approved', 'reversed') OR receipt_no IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_payments_receipt_only_when_approved"),
        "payments",
        "receipt_no IS NULL OR status IN ('approved', 'reversed')",
    )
    op.create_check_constraint(
        op.f("ck_payments_receipt_no_format"),
        "payments",
        "receipt_no IS NULL OR receipt_no ~ '^RCPT/[0-9]{4}-[0-9]{2}/[0-9]{6,}$'",
    )
    op.create_check_constraint(
        op.f("ck_payments_rejected_complete"),
        "payments",
        "status <> 'rejected' OR (rejected_by IS NOT NULL AND rejected_at IS NOT NULL "
        "AND rejection_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_payments_reversed_complete"),
        "payments",
        "status <> 'reversed' OR (reversed_by IS NOT NULL AND reversed_at IS NOT NULL "
        "AND receipt_cancelled_at IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_payments_upi_has_reference"),
        "payments",
        "method <> 'upi' OR reference IS NOT NULL",
    )
    op.create_index("ix_payments_pay_request_id", "payments", ["pay_request_id"])

    # --- Reversal requests (Q4) ------------------------------------------------------------------
    op.create_table(
        "reversal_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column("allocation_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint(
            "(payment_id IS NULL) <> (allocation_id IS NULL)",
            name=op.f("ck_reversal_requests_one_target"),
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('approved', 'rejected')",
            name=op.f("ck_reversal_requests_decision_valid"),
        ),
        sa.CheckConstraint(
            "(decision IS NULL) = (decided_by IS NULL AND decided_at IS NULL)",
            name=op.f("ck_reversal_requests_decision_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_reversal_requests_payment_id_payments")
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["payment_allocations.id"],
            name=op.f("fk_reversal_requests_allocation_id_payment_allocations"),
        ),
        _user_fk("reversal_requests", "requested_by"),
        _user_fk("reversal_requests", "decided_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reversal_requests")),
    )
    op.execute(
        "CREATE UNIQUE INDEX one_pending_reversal_per_payment ON reversal_requests (payment_id) "
        "WHERE decision IS NULL AND payment_id IS NOT NULL"
    )

    # --- Receipt numbers (no gaps) ---------------------------------------------------------------
    op.create_table(
        "receipt_counters",
        sa.Column("financial_year", sa.Text(), nullable=False),
        sa.Column("last_number", sa.BigInteger(), nullable=False),
        _updated_at(),
        _created_at(),
        sa.CheckConstraint(
            "financial_year ~ '^[0-9]{4}-[0-9]{2}$'",
            name=op.f("ck_receipt_counters_financial_year_format"),
        ),
        sa.CheckConstraint("last_number >= 1", name=op.f("ck_receipt_counters_last_positive")),
        sa.PrimaryKeyConstraint("financial_year", name=op.f("pk_receipt_counters")),
    )

    # --- Advance (rule 5) ------------------------------------------------------------------------
    op.create_check_constraint(
        op.f("ck_advance_transactions_sign_follows_kind"),
        "advance_transactions",
        "(kind = 'deposit') = (amount_paise > 0)",
    )
    op.create_index(
        "ix_payment_allocations_advance_transaction_id",
        "payment_allocations",
        ["advance_transaction_id"],
    )
    op.execute(
        """
        CREATE FUNCTION advance_balance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (SELECT coalesce(sum(amount_paise), 0) FROM advance_transactions
              WHERE driver_id = NEW.driver_id AND status = 'approved') < 0 THEN
            RAISE EXCEPTION 'the advance balance cannot go below 0'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER advance_balance_not_negative "
        "AFTER INSERT OR UPDATE ON advance_transactions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION advance_balance_guard()"
    )

    _documents((*_OWNER_TYPES_0007, "payment"), (*_DOC_TYPES_0007, "payment_proof"))


def downgrade() -> None:
    has_proofs = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM documents WHERE owner_type = 'payment')")
    )
    if has_proofs:
        raise RuntimeError("Payment proof documents exist; downgrade 0008 would orphan them.")
    _documents(_OWNER_TYPES_0007, _DOC_TYPES_0007)
    op.execute("DROP TRIGGER advance_balance_not_negative ON advance_transactions")
    op.execute("DROP FUNCTION advance_balance_guard()")
    op.drop_index("ix_payment_allocations_advance_transaction_id", "payment_allocations")
    op.drop_constraint(
        op.f("ck_advance_transactions_sign_follows_kind"), "advance_transactions", type_="check"
    )
    op.drop_table("receipt_counters")
    op.drop_table("reversal_requests")
    op.drop_index("ix_payments_pay_request_id", "payments")
    for name in (
        "ck_payments_upi_has_reference",
        "ck_payments_reversed_complete",
        "ck_payments_rejected_complete",
        "ck_payments_receipt_no_format",
        "ck_payments_receipt_only_when_approved",
        "ck_payments_approved_has_receipt",
    ):
        op.drop_constraint(op.f(name), "payments", type_="check")
    op.drop_constraint("fk_payments_reversed_by_users", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_rejected_by_users", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_pay_request_id_pay_requests", "payments", type_="foreignkey")
    for column in (
        "receipt_cancelled_at",
        "reversed_at",
        "reversed_by",
        "rejected_at",
        "rejected_by",
    ):
        op.drop_column("payments", column)
    op.drop_table("pay_requests")
