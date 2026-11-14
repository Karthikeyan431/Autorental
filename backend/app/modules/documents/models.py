"""Encrypted documents and their access log (docs/kyc.md "Documents", docs/security.md)."""

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, TimestampMixin

OWNER_TYPES = ("driver", "kyc_check", "vehicle", "agreement", "payment")
# driver_photo belongs to a driver, vehicle_paper to a vehicle (0006), signed_agreement to an
# agreement (0007); the others to a KYC attempt
# (screenshots: Week 4, 0005).
DOC_TYPES = (
    "driver_photo",
    "id_front",
    "id_back",
    "licence_front",
    "licence_back",
    "lookup_screenshot",
    "attestation_screenshot",
    "vehicle_paper",
    "signed_agreement",
    "payment_proof",  # owner_type payment (0008)
)
MIME_TYPES = ("image/jpeg", "image/png", "application/pdf")
ACCESS_PURPOSES = ("view", "download")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"owner_type IN ({_sql_list(OWNER_TYPES)})", name="owner_type_valid"),
        CheckConstraint(f"doc_type IN ({_sql_list(DOC_TYPES)})", name="doc_type_valid"),
        CheckConstraint(f"mime_type IN ({_sql_list(MIME_TYPES)})", name="mime_type_valid"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        Index("ix_documents_owner", "owner_type", "owner_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retention_until: Mapped[date | None] = mapped_column(Date)  # Q27: kept until the owner decides
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentAccessLog(CreatedAtMixin, Base):
    """Insert-only: one row for every view or download (migration 0003 revokes UPDATE/DELETE)."""

    __tablename__ = "document_access_log"
    __table_args__ = (
        CheckConstraint(f"purpose IN ({_sql_list(ACCESS_PURPOSES)})", name="purpose_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
