"""Session (refresh-token family) revocation, shared by the auth and users services."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core import time as clock
from app.modules.auth.models import AuthSession


def revoke_family(session: Session, family_id: str, reason: str) -> None:
    session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=clock.utc_now(), revoked_reason=reason)
    )


def revoke_user_sessions(
    session: Session, user_id: int, reason: str, *, keep_family: str | None = None
) -> None:
    """Revoke every live refresh token of a user (optionally keeping the current family)."""
    statement = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_family is not None:
        statement = statement.where(AuthSession.family_id != keep_family)
    session.execute(statement.values(revoked_at=clock.utc_now(), revoked_reason=reason))
