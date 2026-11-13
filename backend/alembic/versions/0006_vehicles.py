"""Autos (Week 4): vehicles, vehicle_compliance (papers) and maintenance_records; documents
gain the owner type `vehicle` and the doc type `vehicle_paper`.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13

* registration_number is stored normalised (upper case letters and digits only) and unique.
* Only the agreements service (Week 5) sets status `rented`; nothing here enforces that in SQL,
  the service does (tests/api/test_vehicles_api.py).
* New tables get app_user's base grants automatically (ALTER DEFAULT PRIVILEGES in 0001).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KYC_DOC_TYPES = (
    "driver_photo",
    "id_front",
    "id_back",
    "licence_front",
    "licence_back",
    "lookup_screenshot",
    "attestation_screenshot",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
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
    ]


def _documents(owner_types: tuple[str, ...], doc_types: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_documents_owner_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_owner_type_valid"), "documents", f"owner_type IN ({_in(owner_types)})"
    )
    op.drop_constraint(op.f("ck_documents_doc_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_doc_type_valid"), "documents", f"doc_type IN ({_in(doc_types)})"
    )


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("registration_number", sa.Text(), nullable=False),
        sa.Column("make", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("fuel_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="available", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "registration_number ~ '^[A-Z0-9]{4,12}$'",
            name=op.f("ck_vehicles_registration_normalised"),
        ),
        sa.CheckConstraint(
            "status IN ('available', 'rented', 'maintenance', 'inactive')",
            name=op.f("ck_vehicles_status_valid"),
        ),
        sa.CheckConstraint(
            "fuel_type IS NULL OR fuel_type IN ('cng', 'lpg', 'petrol', 'diesel', 'electric')",
            name=op.f("ck_vehicles_fuel_type_valid"),
        ),
        sa.CheckConstraint(
            "year IS NULL OR year BETWEEN 1980 AND 2100", name=op.f("ck_vehicles_year_range")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_vehicles_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint("registration_number", name=op.f("uq_vehicles_registration_number")),
    )
    op.create_table(
        "vehicle_compliance",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("recorded_by", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('insurance', 'fitness', 'permit', 'pollution')",
            name=op.f("ck_vehicle_compliance_kind_valid"),
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_from <= valid_until",
            name=op.f("ck_vehicle_compliance_valid_from_before_until"),
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], name=op.f("fk_vehicle_compliance_vehicle_id_vehicles")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_vehicle_compliance_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name=op.f("fk_vehicle_compliance_recorded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_compliance")),
    )
    op.create_index(
        "ix_vehicle_compliance_vehicle_kind", "vehicle_compliance", ["vehicle_id", "kind"]
    )
    op.create_table(
        "maintenance_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("vehicle_id", sa.BigInteger(), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost_paise", sa.BigInteger(), nullable=True),
        sa.Column("recorded_by", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= started_on",
            name=op.f("ck_maintenance_records_ended_after_started"),
        ),
        sa.CheckConstraint(
            "cost_paise IS NULL OR cost_paise >= 0",
            name=op.f("ck_maintenance_records_cost_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], name=op.f("fk_maintenance_records_vehicle_id_vehicles")
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name=op.f("fk_maintenance_records_recorded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_records")),
    )
    op.create_index(
        op.f("ix_maintenance_records_vehicle_id"), "maintenance_records", ["vehicle_id"]
    )
    _documents(("driver", "kyc_check", "vehicle"), (*_KYC_DOC_TYPES, "vehicle_paper"))


def downgrade() -> None:
    op.drop_index(op.f("ix_maintenance_records_vehicle_id"), table_name="maintenance_records")
    op.drop_table("maintenance_records")
    op.drop_index("ix_vehicle_compliance_vehicle_kind", table_name="vehicle_compliance")
    op.drop_table("vehicle_compliance")
    op.drop_table("vehicles")
    # Vehicle paper documents may have insert-only access-log rows, so they are never deleted
    # here: the downgrade stops instead of losing history.
    has_papers = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM documents WHERE owner_type = 'vehicle')")
    )
    if has_papers:
        raise RuntimeError("Vehicle paper documents exist; downgrade 0006 would orphan them.")
    _documents(("driver", "kyc_check"), _KYC_DOC_TYPES)
