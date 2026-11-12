"""Insert-only audit log with a SHA-256 hash chain (rule 11, docs/security.md).

Each row stores the previous row's hash and its own hash over the canonical JSON of its
contents, so editing, deleting or reordering rows is detected by `verify_chain()`.

`write_audit()` always uses the caller's session: the entry is part of the same database
transaction as the change it records, so a rolled-back change leaves no audit entry. It does
not commit. A transaction-scoped advisory lock makes concurrent writers take turns, so the
chain never forks.
"""

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, Index, Text, select, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, CreatedAtMixin
from app.core.redaction import redact
from app.core.request_context import get_request_id
from app.core.time import utc_now

GENESIS_HASH = "0" * 64
_AUDIT_LOCK_KEY = 7_204_211_001  # arbitrary constant shared by every writer


class AuditLog(CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_occurred_at", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[Any | None] = mapped_column(JSONB)
    after: Mapped[Any | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)


def _jsonable(value: Any) -> Any:
    """Normalise a value to JSON that survives a JSONB round trip unchanged."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise TypeError("Floats are not allowed in audit data; money is integer paise.")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("Naive datetimes are not allowed in audit data.")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    raise TypeError(f"Cannot store {type(value).__name__} in audit data.")


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, UTF-8 text: the same data always gives the same string."""
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalise_ip(ip: Any) -> str | None:
    if ip is None:
        return None
    return str(ipaddress.ip_address(str(ip)))


def _hashed_fields(
    *,
    occurred_at: datetime,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    before: Any,
    after: Any,
    reason: str | None,
    ip: str | None,
    request_id: str | None,
    prev_hash: str,
) -> dict[str, Any]:
    return {
        "occurred_at": occurred_at,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": before,
        "after": after,
        "reason": reason,
        "ip": ip,
        "request_id": request_id,
        "prev_hash": prev_hash,
    }


def compute_hash(fields: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(fields).encode("utf-8")).hexdigest()


def write_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    actor_id: int | None = None,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    occurred_at: datetime | None = None,
) -> AuditLog:
    """Add an audit entry to the caller's transaction (it is not committed here)."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _AUDIT_LOCK_KEY})
    last_hash = session.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))

    fields = _hashed_fields(
        occurred_at=(occurred_at or utc_now()).astimezone(UTC),
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=_jsonable(redact(before)),
        after=_jsonable(redact(after)),
        reason=reason,
        ip=_normalise_ip(ip),
        request_id=request_id if request_id is not None else get_request_id(),
        prev_hash=last_hash or GENESIS_HASH,
    )
    entry = AuditLog(**fields, hash=compute_hash(fields))
    session.add(entry)
    session.flush()
    return entry


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    checked: int
    first_bad_id: int | None = None


def verify_chain(session: Session) -> ChainVerification:
    """Recompute every hash in id order. Reports the first row that does not verify."""
    expected_prev = GENESIS_HASH
    checked = 0
    rows = session.execute(select(AuditLog).order_by(AuditLog.id).execution_options(yield_per=500))
    for entry in rows.scalars():
        fields = _hashed_fields(
            occurred_at=entry.occurred_at,
            actor_id=entry.actor_id,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            before=entry.before,
            after=entry.after,
            reason=entry.reason,
            ip=_normalise_ip(entry.ip),
            request_id=entry.request_id,
            prev_hash=entry.prev_hash,
        )
        if entry.prev_hash != expected_prev or compute_hash(fields) != entry.hash:
            return ChainVerification(ok=False, checked=checked, first_bad_id=entry.id)
        expected_prev = entry.hash
        checked += 1
    return ChainVerification(ok=True, checked=checked)
