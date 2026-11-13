"""Password hashing (Argon2id) and the password policy (docs/security.md)."""

import pytest

from app.core.errors import AppError
from app.core.security import (
    COMMON_PASSWORDS_FILE,
    MIN_PASSWORD_LENGTH,
    check_password_policy,
    generate_temporary_password,
    hash_password,
    is_common_password,
    verify_password,
)


def test_hashes_are_argon2id_and_salted() -> None:
    first = hash_password("Correct-horse-0001")
    second = hash_password("Correct-horse-0001")
    assert first.startswith("$argon2id$")
    assert first != second
    assert "Correct-horse-0001" not in first


def test_verify_accepts_the_right_password_only() -> None:
    hashed = hash_password("Correct-horse-0001")
    assert verify_password(hashed, "Correct-horse-0001") is True
    assert verify_password(hashed, "correct-horse-0001") is False
    assert verify_password("not-a-hash", "Correct-horse-0001") is False


def test_minimum_length_is_10() -> None:
    assert MIN_PASSWORD_LENGTH == 10
    with pytest.raises(AppError) as short:
        check_password_policy("Abcdef-12")
    assert short.value.code == "PASSWORD_TOO_SHORT"
    check_password_policy("Abcdef-123")


def test_maximum_length_is_bounded() -> None:
    with pytest.raises(AppError) as long:
        check_password_policy("x" * 129)
    assert long.value.code == "PASSWORD_TOO_LONG"


def test_the_bundled_list_has_10000_common_passwords() -> None:
    lines = [line for line in COMMON_PASSWORDS_FILE.read_text("utf-8").splitlines() if line]
    assert len(lines) >= 10_000


@pytest.mark.parametrize(
    "password", ["1234567890", "qwertyuiop", "CHARLIE123", "Basketball", "Password1"]
)
def test_common_passwords_are_refused_in_any_case(password: str) -> None:
    assert is_common_password(password)
    if len(password) >= MIN_PASSWORD_LENGTH:
        with pytest.raises(AppError) as common:
            check_password_policy(password)
        assert common.value.code == "PASSWORD_TOO_COMMON"


def test_temporary_passwords_pass_the_policy_and_differ() -> None:
    values = {generate_temporary_password() for _ in range(20)}
    assert len(values) == 20
    for value in values:
        check_password_policy(value)
        assert len(value) >= 12
