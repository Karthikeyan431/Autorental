"""Staff management (owner only) and the first-run owner account.

Rules:
* Exactly one owner (partial unique index); the owner cannot be deactivated, and their
  permissions are fixed (all of them).
* Up to `staff_limit` active staff (rule 16), checked on create and reactivate under an
  advisory lock so two requests cannot both pass the check.
* Owner-only permission codes can never be granted (409 here, plus a database CHECK).
* Deactivation and password resets revoke every session in the same transaction.

Audit entries never contain names, mobiles, emails or passwords: only ids, flags, permission
codes and the names of the fields that changed.
"""

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.pagination import LIKE_ESCAPE, Page, PageParams, escape_like
from app.core.permissions import (
    OWNER_ONLY,
    STAFF_DEFAULTS,
    Permission,
    effective_permissions,
)
from app.core.phone import normalise_mobile
from app.core.security import (
    check_password_policy,
    generate_temporary_password,
    hash_password,
)
from app.modules.auth.sessions import revoke_user_sessions
from app.modules.settings.schemas import SettingsValues
from app.modules.settings.service import get_current_settings
from app.modules.users.models import User, UserPermission
from app.modules.users.schemas import StaffUpdate, UserOut, clean_email

_STAFF_LIMIT_LOCK_KEY = 7_204_211_002


def _not_found() -> AppError:
    return AppError("NOT_FOUND", "Not found.", status_code=404)


def _mobile_or_error(value: str) -> str:
    try:
        return normalise_mobile(value)
    except ValueError as exc:
        raise AppError("INVALID_MOBILE", str(exc), status_code=422) from exc


def _email_or_error(value: str | None) -> str | None:
    try:
        return clean_email(value)
    except ValueError as exc:
        raise AppError("INVALID_EMAIL", str(exc), status_code=422) from exc


def granted_codes(session: Session, user_id: int) -> list[str]:
    return sorted(
        session.scalars(
            select(UserPermission.permission_code).where(UserPermission.user_id == user_id)
        ).all()
    )


def user_out(session: Session, user: User) -> UserOut:
    permissions = effective_permissions(user.role, granted_codes(session, user.id))
    return UserOut(
        id=user.id,
        name=user.name,
        mobile=user.mobile,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        totp_enabled=user.totp_secret is not None,
        last_login_at=user.last_login_at,
        deactivated_at=user.deactivated_at,
        created_at=user.created_at,
        permissions=sorted(permissions),
    )


def _ensure_unique(
    session: Session, *, mobile: str | None, email: str | None, exclude_id: int | None
) -> None:
    others = select(User.id).where(User.id != exclude_id) if exclude_id else select(User.id)
    if mobile is not None and session.scalar(others.where(User.mobile == mobile).limit(1)):
        raise AppError("MOBILE_TAKEN", "Another account already uses this mobile number.")
    if email is not None and session.scalar(others.where(User.email == email).limit(1)):
        raise AppError("EMAIL_TAKEN", "Another account already uses this email address.")


def staff_limit(session: Session) -> int:
    current = get_current_settings(session)
    if current is not None:
        return current.staff_limit
    default: int = SettingsValues.model_fields["staff_limit"].default
    return default


def _check_staff_limit(session: Session) -> None:
    """Refuse when the active staff count has reached the limit (rule 16)."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STAFF_LIMIT_LOCK_KEY})
    active = session.scalar(
        select(func.count()).select_from(User).where(User.role == "staff", User.is_active)
    )
    limit = staff_limit(session)
    if (active or 0) >= limit:
        raise AppError(
            "STAFF_LIMIT_REACHED",
            f"You already have {limit} active staff, the most allowed. "
            "Deactivate someone or raise the staff limit in Settings.",
            details={"staff_limit": limit, "active_staff": active or 0},
        )


def owner_exists(session: Session) -> bool:
    return session.scalar(select(User.id).where(User.role == "owner").limit(1)) is not None


def create_owner(
    session: Session, *, name: str, mobile: str, email: str | None, password: str
) -> User:
    """First-run owner account (CLI). TOTP is set up at the first browser sign-in."""
    if owner_exists(session):
        raise AppError("OWNER_EXISTS", "An owner account already exists.")
    normalised = _mobile_or_error(mobile)
    cleaned_email = _email_or_error(email)
    check_password_policy(password, name=name, mobile=normalised)
    _ensure_unique(session, mobile=normalised, email=cleaned_email, exclude_id=None)

    user = User(
        name=" ".join(name.split()),
        mobile=normalised,
        email=cleaned_email,
        password_hash=hash_password(password),
        role="owner",
        password_changed_at=clock.utc_now(),
    )
    session.add(user)
    session.flush()
    write_audit(
        session,
        action="user.owner_created",
        entity_type="user",
        entity_id=user.id,
        actor_id=None,
        after={"role": "owner", "is_active": True},
        reason="First-run command",
    )
    return user


def create_staff(
    session: Session,
    *,
    actor_id: int | None,
    name: str,
    mobile: str,
    email: str | None,
    password: str | None = None,
    must_change_password: bool = True,
    ip: str | None = None,
) -> tuple[User, str | None]:
    """Create a staff member with the default permissions.

    Without `password`, a temporary password is generated and returned once (the API path).
    """
    normalised = _mobile_or_error(mobile)
    email = _email_or_error(email)
    _ensure_unique(session, mobile=normalised, email=email, exclude_id=None)
    _check_staff_limit(session)

    temporary = None
    if password is None:
        temporary = generate_temporary_password()
        password = temporary
        must_change_password = True
    else:
        check_password_policy(password, name=name, mobile=normalised)

    user = User(
        name=name,
        mobile=normalised,
        email=email,
        password_hash=hash_password(password),
        role="staff",
        must_change_password=must_change_password,
        password_changed_at=clock.utc_now(),
    )
    session.add(user)
    session.flush()
    for code in sorted(STAFF_DEFAULTS):
        session.add(
            UserPermission(user_id=user.id, permission_code=code.value, granted_by=actor_id)
        )
    session.flush()

    write_audit(
        session,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        after={
            "role": "staff",
            "is_active": True,
            "must_change_password": must_change_password,
            "permissions": sorted(code.value for code in STAFF_DEFAULTS),
        },
        ip=ip,
    )
    return user, temporary


def get_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise _not_found()
    return user


def _get_for_update(session: Session, user_id: int) -> User:
    user = session.get(User, user_id, with_for_update=True)
    if user is None:
        raise _not_found()
    return user


def list_users(
    session: Session,
    params: PageParams,
    *,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    query = select(User)
    if search and search.strip():
        term = f"%{escape_like(search.strip())}%"
        digits = "".join(ch for ch in search if ch.isdigit())
        conditions = [
            User.name.ilike(term, escape=LIKE_ESCAPE),
            User.email.ilike(term, escape=LIKE_ESCAPE),
        ]
        if len(digits) >= 3:
            conditions.append(User.mobile.like(f"%{digits}%"))
        query = query.where(or_(*conditions))
    if role is not None:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = session.scalars(
        query.order_by(User.role.asc(), User.name.asc(), User.id.asc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return Page(
        items=[user_out(session, user) for user in users],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def update_user(
    session: Session, *, actor_id: int, user_id: int, changes: StaffUpdate, ip: str | None = None
) -> User:
    user = _get_for_update(session, user_id)
    fields = changes.model_fields_set
    new_mobile = changes.mobile if "mobile" in fields else None
    new_email = changes.email if "email" in fields else None
    _ensure_unique(session, mobile=new_mobile, email=new_email, exclude_id=user.id)

    changed: list[str] = []
    if "name" in fields and changes.name is not None and changes.name != user.name:
        user.name = changes.name
        changed.append("name")
    if new_mobile is not None and new_mobile != user.mobile:
        user.mobile = new_mobile
        changed.append("mobile")
    if "email" in fields and changes.email != user.email:
        user.email = changes.email
        changed.append("email")
    if not changed:
        return user

    session.flush()
    write_audit(
        session,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        after={"changed_fields": changed},
        ip=ip,
    )
    return user


def deactivate_user(
    session: Session, *, actor_id: int, user_id: int, reason: str | None, ip: str | None = None
) -> User:
    user = _get_for_update(session, user_id)
    if user.role == "owner":
        raise AppError("OWNER_CANNOT_BE_DEACTIVATED", "The owner account cannot be deactivated.")
    if not user.is_active:
        raise AppError("USER_ALREADY_INACTIVE", "This staff member is already inactive.")
    user.is_active = False
    user.deactivated_at = clock.utc_now()
    revoke_user_sessions(session, user.id, "deactivated")
    session.flush()
    write_audit(
        session,
        action="user.deactivated",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        before={"is_active": True},
        after={"is_active": False},
        reason=reason,
        ip=ip,
    )
    return user


def reactivate_user(
    session: Session, *, actor_id: int, user_id: int, ip: str | None = None
) -> User:
    user = _get_for_update(session, user_id)
    if user.is_active:
        raise AppError("USER_ALREADY_ACTIVE", "This staff member is already active.")
    _check_staff_limit(session)
    user.is_active = True
    user.deactivated_at = None
    user.failed_logins = 0
    user.locked_until = None
    session.flush()
    write_audit(
        session,
        action="user.reactivated",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        before={"is_active": False},
        after={"is_active": True},
        ip=ip,
    )
    return user


def reset_password(session: Session, *, actor_id: int, user_id: int, ip: str | None = None) -> str:
    """Set a temporary password, force a change at next sign-in, sign out everywhere."""
    user = _get_for_update(session, user_id)
    if user.role == "owner":
        raise AppError(
            "OWNER_PASSWORD_RESET_NOT_ALLOWED",
            "The owner changes their own password from their account.",
        )
    temporary = generate_temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.password_changed_at = clock.utc_now()
    user.failed_logins = 0
    user.locked_until = None
    revoke_user_sessions(session, user.id, "password_reset")
    session.flush()
    write_audit(
        session,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        after={"must_change_password": True},
        ip=ip,
    )
    return temporary


def set_permissions(
    session: Session,
    *,
    actor_id: int,
    user_id: int,
    permissions: list[Permission],
    ip: str | None = None,
) -> User:
    user = _get_for_update(session, user_id)
    if user.role == "owner":
        raise AppError(
            "OWNER_PERMISSIONS_FIXED", "The owner always has every permission.", status_code=409
        )
    refused = sorted({p.value for p in permissions if p in OWNER_ONLY})
    if refused:
        raise AppError(
            "PERMISSION_NOT_GRANTABLE",
            "Owner-only permissions cannot be given to staff.",
            details={"codes": refused},
        )

    wanted = sorted({p.value for p in permissions})
    before = granted_codes(session, user.id)
    if wanted == before:
        return user

    rows = session.scalars(select(UserPermission).where(UserPermission.user_id == user.id)).all()
    for row in rows:
        if row.permission_code not in wanted:
            session.delete(row)
    for code in wanted:
        if code not in before:
            session.add(UserPermission(user_id=user.id, permission_code=code, granted_by=actor_id))
    session.flush()
    write_audit(
        session,
        action="user.permissions_changed",
        entity_type="user",
        entity_id=user.id,
        actor_id=actor_id,
        before={"permissions": before},
        after={"permissions": wanted},
        ip=ip,
    )
    return user
