"""Signed tokens (HS256 with SECRET_KEY) and opaque refresh tokens.

* Access token: 15 minutes, `typ=access`, `sub` = user id, `sid` = session family id.
* Challenge token: 5 minutes, `typ=challenge`, issued after the owner's password is checked.
  `purpose` is `totp` (enter a code) or `totp_setup` (first sign-in: may only set up TOTP).
* Refresh token: a random string; only its SHA-256 is stored (in `sessions`).

Expiry is checked against `app.core.time.utc_now()`, so tests can move the clock.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import jwt

from app.core import time as clock

ACCESS_TOKEN_TTL = timedelta(minutes=15)
CHALLENGE_TTL = timedelta(minutes=5)
REFRESH_TOKEN_TTL = timedelta(days=7)
_ALGORITHM = "HS256"

ChallengePurpose = Literal["totp", "totp_setup"]


class TokenError(Exception):
    """Invalid, expired or wrong-type token."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    family_id: str


@dataclass(frozen=True)
class ChallengeClaims:
    user_id: int
    purpose: ChallengePurpose


def _encode(payload: dict[str, Any], key: str, ttl: timedelta) -> str:
    expires = clock.utc_now() + ttl
    return jwt.encode({**payload, "exp": int(expires.timestamp())}, key, algorithm=_ALGORITHM)


def _decode(token: str, key: str, typ: str) -> dict[str, Any]:
    if not key:
        raise TokenError("No signing key configured.")
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False, "require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token.") from exc
    if claims.get("typ") != typ:
        raise TokenError("Wrong token type.")
    exp = claims["exp"]
    if not isinstance(exp, int) or exp <= int(clock.utc_now().timestamp()):
        raise TokenError("Token expired.")
    return claims


def _require_key(key: str) -> str:
    if not key:
        raise TokenError("No signing key configured.")
    return key


def make_access_token(key: str, *, user_id: int, family_id: str) -> str:
    return _encode(
        {"typ": "access", "sub": str(user_id), "sid": family_id},
        _require_key(key),
        ACCESS_TOKEN_TTL,
    )


def read_access_token(key: str, token: str) -> AccessClaims:
    claims = _decode(token, key, "access")
    try:
        return AccessClaims(user_id=int(claims["sub"]), family_id=str(claims["sid"]))
    except (KeyError, ValueError) as exc:
        raise TokenError("Invalid token.") from exc


def make_challenge_token(key: str, *, user_id: int, purpose: ChallengePurpose) -> str:
    return _encode(
        {"typ": "challenge", "sub": str(user_id), "purpose": purpose, "jti": uuid.uuid4().hex},
        _require_key(key),
        CHALLENGE_TTL,
    )


def read_challenge_token(key: str, token: str) -> ChallengeClaims:
    claims = _decode(token, key, "challenge")
    purpose = claims.get("purpose")
    if purpose not in ("totp", "totp_setup"):
        raise TokenError("Invalid token.")
    try:
        return ChallengeClaims(user_id=int(claims["sub"]), purpose=purpose)
    except ValueError as exc:
        raise TokenError("Invalid token.") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def refresh_expiry(now: datetime) -> datetime:
    return now + REFRESH_TOKEN_TTL
