"""Passwords: Argon2id hashing and the policy (docs/security.md).

* At least 10 characters, at most 128.
* Not one of the 10,000 most common passwords (SecLists, MIT licence; compared ignoring case).
* Hashes are Argon2id with argon2-cffi's default (RFC 9106 low-memory) parameters.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import AppError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
COMMON_PASSWORDS_FILE = Path(__file__).with_name("data") / "common-passwords.txt"

# No look-alike characters (0/O, 1/l/I), so a temporary password can be read out loud.
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
_TEMP_LENGTH = 14

_hasher = PasswordHasher()


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    text = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8")
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


def is_common_password(password: str) -> bool:
    return password.strip().lower() in _common_passwords()


def check_password_policy(password: str) -> None:
    """Raise a 422 AppError naming the rule the password breaks. The password is never echoed."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(
            "PASSWORD_TOO_SHORT",
            f"Use at least {MIN_PASSWORD_LENGTH} characters.",
            status_code=422,
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AppError(
            "PASSWORD_TOO_LONG",
            f"Use at most {MAX_PASSWORD_LENGTH} characters.",
            status_code=422,
        )
    if is_common_password(password):
        raise AppError(
            "PASSWORD_TOO_COMMON",
            "This password is too common. Choose a less predictable one.",
            status_code=422,
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# Verified against when the account does not exist, so the response time does not reveal it.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def generate_temporary_password() -> str:
    while True:
        value = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(_TEMP_LENGTH))
        if not is_common_password(value):
            return value
