"""Insert-only audit log with a SHA-256 hash chain (rule 11)."""

import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import (
    GENESIS_HASH,
    AuditLog,
    canonical_json,
    verify_chain,
    write_audit,
)
from app.core.redaction import REDACTED


def test_canonical_json_ignores_key_order() -> None:
    assert canonical_json({"b": 1, "a": {"y": 2, "x": 3}}) == canonical_json(
        {"a": {"x": 3, "y": 2}, "b": 1}
    )


def test_canonical_json_is_compact_and_unicode() -> None:
    assert canonical_json({"a": "₹300", "b": [1, None, True]}) == '{"a":"₹300","b":[1,null,true]}'


def test_canonical_json_refuses_floats() -> None:
    with pytest.raises(TypeError):
        canonical_json({"amount": 300.0})


def test_three_entries_chain_correctly(db: Session) -> None:
    entries = [
        write_audit(db, action="test.chain", entity_type="test", entity_id=i, after={"n": i})
        for i in range(3)
    ]
    db.flush()
    assert entries[1].prev_hash == entries[0].hash
    assert entries[2].prev_hash == entries[1].hash
    assert len({e.hash for e in entries}) == 3
    result = verify_chain(db)
    assert result.ok
    assert result.checked >= 3


def test_first_entry_links_to_the_genesis_hash(owner_db: Session) -> None:
    # As the schema owner, empty the table inside this rolled-back transaction.
    owner_db.execute(text("DELETE FROM audit_logs"))
    entry = write_audit(owner_db, action="test.genesis", entity_type="test")
    owner_db.flush()
    assert entry.prev_hash == GENESIS_HASH


def test_changing_one_row_breaks_verification(owner_db: Session) -> None:
    owner_db.execute(text("DELETE FROM audit_logs"))
    entries = [
        write_audit(owner_db, action="test.tamper", entity_type="test", after={"n": i})
        for i in range(3)
    ]
    owner_db.flush()
    assert verify_chain(owner_db).ok

    owner_db.execute(
        text("UPDATE audit_logs SET after = '{\"n\": 99}'::jsonb WHERE id = :id"),
        {"id": entries[1].id},
    )
    owner_db.expire_all()
    result = verify_chain(owner_db)
    assert not result.ok
    assert result.first_bad_id == entries[1].id


def test_deleting_a_row_breaks_verification(owner_db: Session) -> None:
    owner_db.execute(text("DELETE FROM audit_logs"))
    entries = [write_audit(owner_db, action="test.delete", entity_type="test") for _ in range(3)]
    owner_db.flush()
    owner_db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": entries[1].id})
    result = verify_chain(owner_db)
    assert not result.ok
    assert result.first_bad_id == entries[2].id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET reason = 'edited'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ],
)
def test_app_user_cannot_change_or_remove_audit_rows(db: Session, statement: str) -> None:
    write_audit(db, action="test.immutable", entity_type="test")
    db.flush()
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text(statement))


def test_personal_fields_are_redacted_in_before_and_after(db: Session) -> None:
    entry = write_audit(
        db,
        action="test.redact",
        entity_type="test",
        before={"mobile": "9000012345", "status": "draft"},
        after={"full_name": "Test Driver 001", "status": "active"},
    )
    db.flush()
    assert entry.before == {"mobile": REDACTED, "status": "draft"}
    assert entry.after == {"full_name": REDACTED, "status": "active"}
    assert verify_chain(db).ok


def test_timestamps_and_ip_round_trip_into_the_hash(db: Session) -> None:
    entry = write_audit(
        db,
        action="test.roundtrip",
        entity_type="test",
        ip="::0001",
        occurred_at=datetime(2026, 11, 12, 4, 30, 0, 123456, tzinfo=UTC),
    )
    db.flush()
    db.expire_all()
    stored = db.get(AuditLog, entry.id)
    assert stored is not None
    assert str(stored.ip) == "::1"
    assert verify_chain(db).ok


def test_rolled_back_change_leaves_no_audit_entry(app_engine: Engine) -> None:
    marker = f"rollback-{uuid.uuid4().hex}"
    with pytest.raises(RuntimeError), Session(app_engine) as session, session.begin():
        write_audit(session, action="test.rollback", entity_type="test", reason=marker)
        session.flush()
        raise RuntimeError("simulated failure after the change")

    with Session(app_engine) as check:
        count = check.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.reason == marker)
        )
    assert count == 0


def test_committed_change_keeps_its_audit_entry(app_engine: Engine) -> None:
    marker = f"commit-{uuid.uuid4().hex}"
    with Session(app_engine) as session, session.begin():
        write_audit(session, action="test.commit", entity_type="test", reason=marker)

    with Session(app_engine) as check:
        count = check.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.reason == marker)
        )
        assert count == 1
        assert verify_chain(check).ok


def test_concurrent_writers_keep_one_unbroken_chain(app_engine: Engine) -> None:
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(10):
                with Session(app_engine) as session, session.begin():
                    write_audit(
                        session,
                        action="test.concurrent",
                        entity_type="test",
                        after={"w": n, "i": i},
                    )
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with Session(app_engine) as check:
        assert verify_chain(check).ok
