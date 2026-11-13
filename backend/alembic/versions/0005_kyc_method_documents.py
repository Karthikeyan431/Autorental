"""KYC method documents (Week 4; D47, docs/kyc.md): the Parivahan lookup screenshot and the
optional masked screenshot of a UIDAI app attestation.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13

Only the documents.doc_type check constraint changes; the method values already exist in
kyc_checks (migration 0003).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("driver_photo", "id_front", "id_back", "licence_front", "licence_back")
_NEW = (*_OLD, "lookup_screenshot", "attestation_screenshot")


def _replace(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_documents_doc_type_valid"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_doc_type_valid"),
        "documents",
        "doc_type IN (" + ", ".join(f"'{v}'" for v in values) + ")",
    )


def upgrade() -> None:
    _replace(_NEW)


def downgrade() -> None:
    op.execute(
        "DELETE FROM documents WHERE doc_type IN ('lookup_screenshot', 'attestation_screenshot')"
    )
    _replace(_OLD)
