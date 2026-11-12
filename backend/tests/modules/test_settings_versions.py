"""Settings are versioned and insert-only (rule 3)."""

from datetime import UTC, datetime, time

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import SettingsChanges
from app.modules.settings.service import create_settings_version, get_current_settings

FAR_FUTURE_NOW = datetime(2100, 1, 1, tzinfo=UTC)


def _snapshot(version: SettingsVersion) -> dict[str, object]:
    return {
        column.key: getattr(version, column.key) for column in SettingsVersion.__table__.columns
    }


def _first_version(db: Session, **changes: object) -> SettingsVersion:
    values: dict[str, object] = {"rent_due_time": time(10, 0), "business_name": "Test Auto Rentals"}
    values.update(changes)
    return create_settings_version(db, SettingsChanges(**values), actor_id=None)  # type: ignore[arg-type]


def test_a_new_version_never_updates_the_old_row(db: Session) -> None:
    v1 = _first_version(db)
    db.flush()
    before = _snapshot(v1)

    v2 = create_settings_version(db, SettingsChanges(rent_due_time=time(11, 0)), actor_id=None)
    db.flush()
    db.expire_all()

    assert v2.id != v1.id
    reloaded = db.get(SettingsVersion, v1.id)
    assert reloaded is not None
    assert _snapshot(reloaded) == before


def test_unchanged_fields_are_copied_from_the_current_version(db: Session) -> None:
    _first_version(db, staff_limit=12, business_name="Test Auto Rentals Copy")
    v2 = create_settings_version(db, SettingsChanges(rent_due_time=time(9, 30)), actor_id=None)
    db.flush()
    assert v2.rent_due_time == time(9, 30)
    assert v2.staff_limit == 12
    assert v2.business_name == "Test Auto Rentals Copy"


def test_defaults_follow_the_data_model(db: Session) -> None:
    v1 = _first_version(db)
    db.flush()
    assert v1.due_day_offset == 0
    assert v1.licence_alert_days == 30
    assert v1.vehicle_alert_days == 30
    assert v1.refunds_enabled is False
    assert v1.staff_limit == 10
    assert v1.pay_request_time == time(8, 0)
    assert v1.weekly_pay_day == 1  # ISO Monday
    assert v1.escalation_suggest_after_days == 1
    assert v1.weekly_mdr_warning_paise == 200000


@pytest.mark.parametrize(
    "statement",
    ["UPDATE settings_versions SET staff_limit = 99", "DELETE FROM settings_versions"],
)
def test_app_user_cannot_update_or_delete_versions(db: Session, statement: str) -> None:
    _first_version(db)
    db.flush()
    with pytest.raises(DBAPIError, match="permission denied"):
        db.execute(text(statement))


def test_current_picks_the_latest_effective_version(db: Session) -> None:
    _first_version(db)
    older = create_settings_version(
        db,
        SettingsChanges(staff_limit=11),
        actor_id=None,
        effective_from=datetime(2099, 1, 1, tzinfo=UTC),
    )
    latest = create_settings_version(
        db,
        SettingsChanges(staff_limit=12),
        actor_id=None,
        effective_from=datetime(2099, 6, 1, tzinfo=UTC),
    )
    create_settings_version(
        db,
        SettingsChanges(staff_limit=13),
        actor_id=None,
        effective_from=datetime(2101, 1, 1, tzinfo=UTC),  # in the future: not current yet
    )
    db.flush()

    current = get_current_settings(db, now=FAR_FUTURE_NOW)
    assert current is not None
    assert current.id == latest.id
    assert current.id != older.id
    assert current.staff_limit == 12


def test_creating_a_version_writes_an_audit_entry_in_the_same_transaction(db: Session) -> None:
    version = _first_version(db)
    db.flush()
    entries = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == "settings_version", AuditLog.entity_id == version.id
        )
    ).all()
    assert len(entries) == 1
    assert entries[0].action == "settings.version_created"
    assert entries[0].after is not None
    assert entries[0].after["rent_due_time"] == "10:00:00"


def test_first_version_requires_a_due_time(owner_db: Session) -> None:
    # As the schema owner, start from an empty table inside this rolled-back transaction.
    owner_db.execute(text("DELETE FROM settings_versions"))
    assert owner_db.scalar(select(func.count()).select_from(SettingsVersion)) == 0
    with pytest.raises(ValidationError):
        create_settings_version(owner_db, SettingsChanges(), actor_id=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"staff_limit": 0},
        {"weekly_pay_day": 8},
        {"weekly_pay_day": 0},
        {"due_day_offset": -1},
        {"licence_alert_days": -5},
        {"weekly_mdr_warning_paise": -1},
    ],
)
def test_invalid_values_are_refused(changes: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        SettingsChanges(**changes)  # type: ignore[arg-type]


def test_money_settings_refuse_floats() -> None:
    with pytest.raises(ValidationError):
        SettingsChanges(weekly_mdr_warning_paise=2000.5)  # type: ignore[arg-type]
