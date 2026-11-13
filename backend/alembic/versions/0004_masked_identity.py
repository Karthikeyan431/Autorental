"""Masked identity (D45, D46, N15, N18): encrypt the driver's address and date of birth and the
date of birth on the licence; add settings_versions.reveal_limit_per_hour.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13

* The three columns become text holding `<key_id>:<ciphertext>` from the field cipher
  (app.core.crypto). Dates are stored as ISO text before encryption.
* The context binds each value to its table, column and row: `drivers.address:<driver id>`,
  `drivers.date_of_birth:<driver id>` and `licence_details.date_of_birth:<driver id>` (the
  licence value follows the driver, like the licence number, so a reopen can copy it).
* Existing rows are encrypted here with FIELD_ENCRYPTION_KEY (only fake development data
  exists). If rows exist and the key is missing, the migration stops. downgrade() decrypts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.config import get_settings
from app.core.crypto import FieldCipher, field_cipher

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cipher() -> FieldCipher:
    try:
        return field_cipher(get_settings())
    except ValueError as exc:
        raise RuntimeError(
            "Migration 0004 needs FIELD_ENCRYPTION_KEY to encrypt existing driver rows. "
            "Run scripts\\db-setup.ps1 (development) or set it in the environment."
        ) from exc


def _has_rows(connection: sa.Connection) -> bool:
    return bool(
        connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM drivers)"))
        or connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM licence_details)"))
    )


def upgrade() -> None:
    connection = op.get_bind()
    op.alter_column(
        "drivers",
        "date_of_birth",
        type_=sa.Text(),
        postgresql_using="to_char(date_of_birth, 'YYYY-MM-DD')",
    )
    op.alter_column(
        "licence_details",
        "date_of_birth",
        type_=sa.Text(),
        postgresql_using="to_char(date_of_birth, 'YYYY-MM-DD')",
    )
    if _has_rows(connection):
        cipher = _cipher()
        drivers = connection.execute(
            sa.text("SELECT id, address, date_of_birth FROM drivers")
        ).all()
        for driver_id, address, dob in drivers:
            connection.execute(
                sa.text("UPDATE drivers SET address = :a, date_of_birth = :d WHERE id = :id"),
                {
                    "id": driver_id,
                    "a": cipher.encrypt(address, context=f"drivers.address:{driver_id}"),
                    "d": cipher.encrypt(dob, context=f"drivers.date_of_birth:{driver_id}"),
                },
            )
        licences = connection.execute(
            sa.text(
                "SELECT id, driver_id, date_of_birth FROM licence_details "
                "WHERE date_of_birth IS NOT NULL"
            )
        ).all()
        for row_id, driver_id, dob in licences:
            connection.execute(
                sa.text("UPDATE licence_details SET date_of_birth = :d WHERE id = :id"),
                {
                    "id": row_id,
                    "d": cipher.encrypt(dob, context=f"licence_details.date_of_birth:{driver_id}"),
                },
            )

    op.add_column(
        "settings_versions",
        sa.Column("reveal_limit_per_hour", sa.Integer(), server_default="30", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_settings_versions_reveal_limit_positive"),
        "settings_versions",
        "reveal_limit_per_hour >= 1",
    )
    # Reveal rate limit: count one user's recent reveal entries quickly.
    op.create_index(
        "ix_audit_logs_actor_action_time",
        "audit_logs",
        ["actor_id", "action", "occurred_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    op.drop_index("ix_audit_logs_actor_action_time", table_name="audit_logs")
    op.drop_constraint(
        op.f("ck_settings_versions_reveal_limit_positive"), "settings_versions", type_="check"
    )
    op.drop_column("settings_versions", "reveal_limit_per_hour")
    if _has_rows(connection):
        cipher = _cipher()
        drivers = connection.execute(
            sa.text("SELECT id, address, date_of_birth FROM drivers")
        ).all()
        for driver_id, address, dob in drivers:
            connection.execute(
                sa.text("UPDATE drivers SET address = :a, date_of_birth = :d WHERE id = :id"),
                {
                    "id": driver_id,
                    "a": cipher.decrypt(address, context=f"drivers.address:{driver_id}"),
                    "d": cipher.decrypt(dob, context=f"drivers.date_of_birth:{driver_id}"),
                },
            )
        licences = connection.execute(
            sa.text(
                "SELECT id, driver_id, date_of_birth FROM licence_details "
                "WHERE date_of_birth IS NOT NULL"
            )
        ).all()
        for row_id, driver_id, dob in licences:
            connection.execute(
                sa.text("UPDATE licence_details SET date_of_birth = :d WHERE id = :id"),
                {
                    "id": row_id,
                    "d": cipher.decrypt(dob, context=f"licence_details.date_of_birth:{driver_id}"),
                },
            )
    op.alter_column(
        "licence_details",
        "date_of_birth",
        type_=sa.Date(),
        postgresql_using="date_of_birth::date",
    )
    op.alter_column(
        "drivers",
        "date_of_birth",
        type_=sa.Date(),
        postgresql_using="date_of_birth::date",
    )
