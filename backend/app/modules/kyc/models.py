"""KYC attempts, their history and the minimal details kept (rule 7, docs/kyc.md).

* One `kyc_checks` row per attempt per check type; exactly one current attempt per driver and
  check type (partial unique index).
* `kyc_events` is insert-only history (migration 0003 revokes UPDATE/DELETE from app_user).
* `identity_details` never holds a full Aadhaar number: `id_last4` is exactly four digits.
* `licence_details.licence_number` is encrypted; `licence_number_hash` (keyed HMAC) finds
  duplicates. An exclusion constraint stops one licence number belonging to two drivers, while
  the same driver's later attempts (a reopen) may repeat it.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, CreatedAtMixin, TimestampMixin

CHECK_TYPES = ("identity", "licence")
METHODS = ("uidai_qr", "uidai_app_attested", "parivahan_lookup", "manual", "demo")
STATUSES = (
    "draft",
    "submitted",
    "under_review",
    "approved",
    "rejected",
    "resubmission_required",
    "expired",
)
# N12: identity documents the owner may accept (setting accepted_id_types; default masked Aadhaar).
ID_DOCUMENT_TYPES = ("masked_aadhaar", "voter_id", "passport")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class KycCheck(TimestampMixin, Base):
    __tablename__ = "kyc_checks"
    __table_args__ = (
        CheckConstraint(f"check_type IN ({_sql_list(CHECK_TYPES)})", name="check_type_valid"),
        CheckConstraint(f"method IN ({_sql_list(METHODS)})", name="method_valid"),
        CheckConstraint(f"status IN ({_sql_list(STATUSES)})", name="status_valid"),
        CheckConstraint("attempt_no >= 1", name="attempt_no_positive"),
        UniqueConstraint("driver_id", "check_type", "attempt_no", name="uq_kyc_checks_attempt"),
        Index(
            "uq_kyc_checks_current",
            "driver_id",
            "check_type",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("drivers.id"), nullable=False, index=True
    )
    check_type: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    review_checklist: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reopened_from_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("kyc_checks.id"))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class KycEvent(CreatedAtMixin, Base):
    __tablename__ = "kyc_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kyc_check_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kyc_checks.id"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))  # NULL = job
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class IdentityDetails(TimestampMixin, Base):
    __tablename__ = "identity_details"
    __table_args__ = (
        CheckConstraint("id_last4 ~ '^[0-9]{4}$'", name="id_last4_four_digits"),
        CheckConstraint(
            f"document_type IN ({_sql_list(ID_DOCUMENT_TYPES)})", name="document_type_valid"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kyc_check_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kyc_checks.id"), nullable=False, unique=True
    )
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    id_last4: Mapped[str] = mapped_column(Text, nullable=False)
    name_on_document: Mapped[str | None] = mapped_column(Text)
    dob_or_yob: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(Text)
    qr_signature_valid: Mapped[bool | None] = mapped_column(Boolean)
    photo_match_confirmed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class LicenceDetails(TimestampMixin, Base):
    __tablename__ = "licence_details"
    __table_args__ = (
        CheckConstraint("licence_number_last4 ~ '^[A-Z0-9]{1,4}$'", name="last4_valid"),
        # The exclusion constraint on (licence_number_hash =, driver_id <>) is created in
        # migration 0003 (btree_gist); SQLAlchemy has no portable spelling for it.
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    kyc_check_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kyc_checks.id"), nullable=False, unique=True
    )
    driver_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("drivers.id"), nullable=False, index=True
    )
    licence_number: Mapped[str] = mapped_column(Text, nullable=False)  # encrypted value
    licence_number_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    licence_number_last4: Mapped[str] = mapped_column(Text, nullable=False)
    name_on_licence: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date | None] = mapped_column(Date)
    valid_until_non_transport: Mapped[date | None] = mapped_column(Date)
    valid_until_transport: Mapped[date | None] = mapped_column(Date)
    vehicle_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    issuing_authority: Mapped[str | None] = mapped_column(Text)
    lookup_status_text: Mapped[str | None] = mapped_column(Text)
    looked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lookup_screenshot_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id")
    )

    def valid_until(self) -> date | None:
        """Q22 default: the transport validity when present, otherwise non-transport."""
        return self.valid_until_transport or self.valid_until_non_transport
