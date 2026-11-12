"""Settings versions: insert-only. Each change writes a new version and an audit entry in the
caller's transaction."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.time import utc_now
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import SettingsChanges, SettingsValues


def get_current_settings(session: Session, now: datetime | None = None) -> SettingsVersion | None:
    """The latest version whose effective_from is at or before `now`."""
    moment = now or utc_now()
    return session.scalars(
        select(SettingsVersion)
        .where(SettingsVersion.effective_from <= moment)
        .order_by(SettingsVersion.effective_from.desc(), SettingsVersion.id.desc())
        .limit(1)
    ).first()


def create_settings_version(
    session: Session,
    changes: SettingsChanges,
    *,
    actor_id: int | None,
    effective_from: datetime | None = None,
    reason: str | None = None,
) -> SettingsVersion:
    """Insert a new version: the current values with `changes` applied. Never updates a row."""
    now = utc_now()
    current = get_current_settings(session, now)
    base = SettingsValues.model_validate(current).model_dump() if current else {}
    values = SettingsValues.model_validate({**base, **changes.model_dump(exclude_unset=True)})

    version = SettingsVersion(
        **values.model_dump(),
        effective_from=effective_from or now,
        created_by=actor_id,
    )
    session.add(version)
    session.flush()

    write_audit(
        session,
        action="settings.version_created",
        entity_type="settings_version",
        entity_id=version.id,
        actor_id=actor_id,
        after={**values.model_dump(), "effective_from": version.effective_from},
        reason=reason,
    )
    return version
