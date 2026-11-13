"""Sign-in, owner TOTP, refresh rotation, logout and password change (docs/security.md).

* Login by mobile or email. 5 failures (wrong password or wrong TOTP code) lock the account
  for 15 minutes. Failures per IP address are throttled (LOGIN_IP_MAX_FAILURES within
  LOGIN_IP_WINDOW_MINUTES).
* Refusals that must be recorded (counters, throttle rows, audit entries, family revocation)
  are raised with `keep_changes=True`, so the request transaction commits them.
* The owner always has a second step. Before TOTP is enrolled, the challenge allows only
  `/auth/totp/setup` and `/auth/totp/confirm`.
* Refresh tokens rotate on every use; presenting a rotated token revokes its whole family.
* Logs and audit entries never contain the login identifier, passwords, tokens or codes.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pyotp
import qrcode
from fastapi import Request
from qrcode.image.svg import SvgPathImage
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.audit import write_audit
from app.core.config import Settings
from app.core.crypto import field_cipher
from app.core.errors import AppError
from app.core.permissions import CurrentUser, effective_permissions, unauthenticated
from app.core.phone import looks_like_email, normalise_mobile
from app.core.security import (
    burn_password_check,
    check_password_policy,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.tokens import (
    ACCESS_TOKEN_TTL,
    ChallengePurpose,
    TokenError,
    hash_token,
    make_access_token,
    make_challenge_token,
    new_csrf_token,
    new_refresh_token,
    read_access_token,
    read_challenge_token,
    refresh_expiry,
)
from app.modules.auth.models import AuthSession, LoginAttempt, RecoveryCode
from app.modules.auth.sessions import revoke_family, revoke_user_sessions
from app.modules.users.models import User
from app.modules.users.schemas import UserOut
from app.modules.users.service import granted_codes, user_out

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
RECOVERY_CODE_COUNT = 10
TOTP_ISSUER = "Auto Rental Manager"

_INVALID_CREDENTIALS = "The mobile number, email or password is not correct."
_LOCKED_MESSAGE = "Too many attempts. Try again in 15 minutes."


# --- Results ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SignInResult:
    access_token: str
    expires_in: int
    refresh_token: str
    csrf_token: str
    user: UserOut


@dataclass(frozen=True)
class ChallengeResult:
    status: str  # "totp_required" | "totp_setup_required"
    challenge_token: str


@dataclass(frozen=True)
class Client:
    ip: str | None
    user_agent: str | None


# --- Helpers ------------------------------------------------------------------------------


def _find_user(session: Session, login_id: str) -> User | None:
    value = login_id.strip()
    if looks_like_email(value):
        return session.scalars(
            select(User).where(func.lower(User.email) == value.lower()).with_for_update()
        ).first()
    try:
        mobile = normalise_mobile(value)
    except ValueError:
        return None
    return session.scalars(select(User).where(User.mobile == mobile).with_for_update()).first()


def _record_attempt(session: Session, client: Client, *, succeeded: bool, now: datetime) -> None:
    session.add(LoginAttempt(ip=client.ip, attempted_at=now, succeeded=succeeded))


def _audit_failure(
    session: Session, client: Client, *, reason: str, user: User | None = None
) -> None:
    write_audit(
        session,
        action="auth.login_failed",
        entity_type="user",
        entity_id=user.id if user else None,
        actor_id=None,
        reason=reason,
        ip=client.ip,
    )


def _refuse_credentials() -> AppError:
    return AppError("INVALID_CREDENTIALS", _INVALID_CREDENTIALS, status_code=401, keep_changes=True)


def _refuse_locked() -> AppError:
    return AppError("ACCOUNT_LOCKED", _LOCKED_MESSAGE, status_code=429, keep_changes=True)


def _refuse_challenge() -> AppError:
    return AppError(
        "CHALLENGE_INVALID",
        "This sign-in step has expired. Please sign in again.",
        status_code=401,
    )


def _is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now


def _register_failure(user: User, now: datetime) -> None:
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.locked_until = now + LOCKOUT
        user.failed_logins = 0


def _check_ip_throttle(session: Session, settings: Settings, client: Client, now: datetime) -> None:
    if client.ip is None:
        return
    since = now - timedelta(minutes=settings.LOGIN_IP_WINDOW_MINUTES)
    failures = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.ip == client.ip,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at > since,
        )
    )
    if (failures or 0) >= settings.LOGIN_IP_MAX_FAILURES:
        _audit_failure(session, client, reason="ip_throttled")
        raise AppError(
            "IP_THROTTLED",
            "Too many sign-in attempts from this network. Try again in 15 minutes.",
            status_code=429,
            keep_changes=True,
        )


def _start_session(
    session: Session, settings: Settings, user: User, client: Client, now: datetime
) -> SignInResult:
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now

    family_id = str(uuid.uuid4())
    refresh_token = new_refresh_token()
    session.add(
        AuthSession(
            user_id=user.id,
            family_id=family_id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=refresh_expiry(now),
            last_used_at=now,
            ip=client.ip,
            user_agent=client.user_agent,
        )
    )
    _record_attempt(session, client, succeeded=True, now=now)
    session.flush()
    write_audit(
        session,
        action="auth.login_succeeded",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        ip=client.ip,
    )
    return SignInResult(
        access_token=make_access_token(
            settings.SECRET_KEY.get_secret_value(), user_id=user.id, family_id=family_id
        ),
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
        refresh_token=refresh_token,
        csrf_token=new_csrf_token(),
        user=user_out(session, user),
    )


def _challenge(settings: Settings, user: User, purpose: ChallengePurpose) -> ChallengeResult:
    token = make_challenge_token(
        settings.SECRET_KEY.get_secret_value(), user_id=user.id, purpose=purpose
    )
    status = "totp_required" if purpose == "totp" else "totp_setup_required"
    return ChallengeResult(status=status, challenge_token=token)


def _secret_context(user: User, column: str) -> str:
    return f"users.{column}:{user.id}"


def _match_totp_step(secret: str, code: str, now: datetime) -> int | None:
    """The time step the code belongs to (current, previous or next window), or None."""
    totp = pyotp.TOTP(secret)
    current = totp.timecode(now)
    for step in (current, current - 1, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _normalise_recovery_code(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _hash_recovery_code(value: str) -> str:
    return hashlib.sha256(_normalise_recovery_code(value).encode("ascii")).hexdigest()


def _new_recovery_code() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _challenge_user(
    session: Session, settings: Settings, token: str, purpose: ChallengePurpose
) -> User:
    try:
        claims = read_challenge_token(settings.SECRET_KEY.get_secret_value(), token)
    except TokenError as exc:
        raise _refuse_challenge() from exc
    if claims.purpose != purpose:
        raise _refuse_challenge()
    user = session.get(User, claims.user_id, with_for_update=True)
    if user is None or not user.is_active or user.role != "owner":
        raise _refuse_challenge()
    enrolled = user.totp_secret is not None
    if (purpose == "totp") != enrolled:
        raise _refuse_challenge()
    return user


def _totp_failure(session: Session, user: User, client: Client, now: datetime) -> AppError:
    _register_failure(user, now)
    _record_attempt(session, client, succeeded=False, now=now)
    _audit_failure(session, client, reason="totp_invalid", user=user)
    return AppError("TOTP_INVALID", "The code is not correct.", status_code=401, keep_changes=True)


# --- Request authentication -----------------------------------------------------------------


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def authenticate_request(session: Session, request: Request) -> CurrentUser:
    """Check the access token, that the user is active and that the session is not revoked."""
    token = _bearer_token(request)
    if token is None:
        raise unauthenticated()
    settings: Settings = request.app.state.settings
    try:
        claims = read_access_token(settings.SECRET_KEY.get_secret_value(), token)
    except TokenError as exc:
        raise unauthenticated() from exc

    user = session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise unauthenticated()
    live = session.scalar(
        select(
            exists().where(
                AuthSession.family_id == claims.family_id,
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > clock.utc_now(),
            )
        )
    )
    if not live:
        raise unauthenticated()
    return CurrentUser(
        id=user.id,
        role=user.role,
        must_change_password=user.must_change_password,
        permissions=effective_permissions(user.role, granted_codes(session, user.id)),
        family_id=claims.family_id,
    )


# --- Sign-in --------------------------------------------------------------------------------


def login(
    session: Session, settings: Settings, *, login_id: str, password: str, client: Client
) -> SignInResult | ChallengeResult:
    now = clock.utc_now()
    _check_ip_throttle(session, settings, client, now)

    user = _find_user(session, login_id)
    if user is None:
        burn_password_check(password)
        _record_attempt(session, client, succeeded=False, now=now)
        _audit_failure(session, client, reason="unknown_account")
        raise _refuse_credentials()

    if _is_locked(user, now):
        _record_attempt(session, client, succeeded=False, now=now)
        _audit_failure(session, client, reason="locked", user=user)
        raise _refuse_locked()

    if not verify_password(user.password_hash, password):
        _register_failure(user, now)
        _record_attempt(session, client, succeeded=False, now=now)
        _audit_failure(session, client, reason="bad_password", user=user)
        raise _refuse_credentials()

    if not user.is_active:
        _record_attempt(session, client, succeeded=False, now=now)
        _audit_failure(session, client, reason="inactive", user=user)
        raise _refuse_credentials()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    if user.role == "owner":
        # The failure counter is reset only after the second step succeeds.
        return _challenge(settings, user, "totp" if user.totp_secret else "totp_setup")
    return _start_session(session, settings, user, client, now)


def complete_totp(
    session: Session,
    settings: Settings,
    *,
    challenge_token: str,
    code: str | None,
    recovery_code: str | None,
    client: Client,
) -> SignInResult:
    now = clock.utc_now()
    user = _challenge_user(session, settings, challenge_token, "totp")
    if _is_locked(user, now):
        raise _refuse_locked()

    if code is not None and user.totp_secret is not None:  # enrolment checked above
        secret = field_cipher(settings).decrypt(
            user.totp_secret, context=_secret_context(user, "totp_secret")
        )
        step = _match_totp_step(secret, code, now)
        if step is None or (user.totp_last_step is not None and step <= user.totp_last_step):
            raise _totp_failure(session, user, client, now)
        user.totp_last_step = step
    elif recovery_code is not None:
        row = session.scalars(
            select(RecoveryCode)
            .where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == _hash_recovery_code(recovery_code),
                RecoveryCode.used_at.is_(None),
            )
            .with_for_update()
        ).first()
        if row is None:
            raise _totp_failure(session, user, client, now)
        row.used_at = now
        write_audit(
            session,
            action="auth.recovery_code_used",
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            ip=client.ip,
        )
    else:  # the schema requires exactly one of code and recovery_code
        raise _totp_failure(session, user, client, now)
    return _start_session(session, settings, user, client, now)


def totp_setup(
    session: Session, settings: Settings, *, challenge_token: str
) -> tuple[str, str, str]:
    """A new pending secret for the owner's authenticator app. Returns (secret, uri, svg)."""
    user = _challenge_user(session, settings, challenge_token, "totp_setup")
    secret = pyotp.random_base32()
    user.totp_pending_secret = field_cipher(settings).encrypt(
        secret, context=_secret_context(user, "totp_pending_secret")
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name="Owner", issuer_name=TOTP_ISSUER)
    image = qrcode.make(uri, image_factory=SvgPathImage, box_size=10, border=2)
    svg = image.to_string(encoding="unicode")
    return secret, uri, str(svg)


def totp_confirm(
    session: Session, settings: Settings, *, challenge_token: str, code: str, client: Client
) -> tuple[SignInResult, list[str]]:
    now = clock.utc_now()
    user = _challenge_user(session, settings, challenge_token, "totp_setup")
    if _is_locked(user, now):
        raise _refuse_locked()
    if user.totp_pending_secret is None:
        raise AppError("TOTP_SETUP_NOT_STARTED", "Start the authenticator setup first.")

    cipher = field_cipher(settings)
    secret = cipher.decrypt(
        user.totp_pending_secret, context=_secret_context(user, "totp_pending_secret")
    )
    step = _match_totp_step(secret, code, now)
    if step is None:
        raise _totp_failure(session, user, client, now)

    user.totp_secret = cipher.encrypt(secret, context=_secret_context(user, "totp_secret"))
    user.totp_pending_secret = None
    user.totp_confirmed_at = now
    user.totp_last_step = step

    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for old in session.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id)):
        session.delete(old)
    session.flush()
    for value in codes:
        session.add(RecoveryCode(user_id=user.id, code_hash=_hash_recovery_code(value)))
    session.flush()
    write_audit(
        session,
        action="auth.totp_enrolled",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        after={"totp_enabled": True, "recovery_codes_issued": RECOVERY_CODE_COUNT},
        ip=client.ip,
    )
    return _start_session(session, settings, user, client, now), codes


# --- Refresh, logout, password change ---------------------------------------------------------


def refresh_session(
    session: Session,
    settings: Settings,
    *,
    refresh_token: str | None,
    csrf_cookie: str | None,
    csrf_header: str | None,
    client: Client,
) -> SignInResult:
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AppError("CSRF_FAILED", "The request could not be verified.", status_code=403)
    invalid = AppError("REFRESH_INVALID", "Please sign in again.", status_code=401)
    if not refresh_token:
        raise invalid

    now = clock.utc_now()
    row = session.scalars(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_token(refresh_token))
        .with_for_update()
    ).first()
    if row is None:
        raise invalid
    if row.revoked_at is not None:
        if row.revoked_reason == "rotated":
            revoke_family(session, row.family_id, "reuse_detected")
            write_audit(
                session,
                action="auth.refresh_reuse_detected",
                entity_type="user",
                entity_id=row.user_id,
                actor_id=None,
                reason="A rotated refresh token was used again; the session family is revoked.",
                ip=client.ip,
            )
            raise AppError(
                "REFRESH_REUSED", "Please sign in again.", status_code=401, keep_changes=True
            )
        raise invalid
    if row.expires_at <= now:
        raise invalid
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise invalid

    new_token = new_refresh_token()
    replacement = AuthSession(
        user_id=user.id,
        family_id=row.family_id,
        refresh_token_hash=hash_token(new_token),
        expires_at=refresh_expiry(now),
        last_used_at=now,
        ip=client.ip,
        user_agent=client.user_agent,
    )
    session.add(replacement)
    session.flush()
    row.revoked_at = now
    row.revoked_reason = "rotated"
    row.replaced_by_id = replacement.id
    row.last_used_at = now
    session.flush()
    return SignInResult(
        access_token=make_access_token(
            settings.SECRET_KEY.get_secret_value(), user_id=user.id, family_id=row.family_id
        ),
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
        refresh_token=new_token,
        csrf_token=new_csrf_token(),
        user=user_out(session, user),
    )


def logout(session: Session, user: CurrentUser, client: Client) -> None:
    revoke_family(session, user.family_id, "logout")
    write_audit(
        session,
        action="auth.logout",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        ip=client.ip,
    )


def change_password(
    session: Session,
    current_user: CurrentUser,
    *,
    current_password: str,
    new_password: str,
    client: Client,
) -> None:
    check_password_policy(new_password)
    user = session.get(User, current_user.id, with_for_update=True)
    if user is None:
        raise unauthenticated()
    if not verify_password(user.password_hash, current_password):
        raise AppError("CURRENT_PASSWORD_INCORRECT", "Your current password is not correct.")
    if hmac.compare_digest(current_password, new_password):
        raise AppError("PASSWORD_UNCHANGED", "Choose a password different from the current one.")

    was_forced = user.must_change_password
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = clock.utc_now()
    revoke_user_sessions(session, user.id, "password_changed", keep_family=current_user.family_id)
    session.flush()
    write_audit(
        session,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        after={"was_forced": was_forced},
        ip=client.ip,
    )
