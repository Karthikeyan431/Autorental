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


@pytest.mark.parametrize(
    "password",
    [
        "Pass-9000000101-x",  # the mobile number
        "x-90000-00101-pass",  # the mobile with separators
        "Ravi@2026xyz!",  # a word of the name, any case
        "RAVIKUMAR-2026!",  # the full name without spaces
        "my-kumar-key-77",  # another word of the name
    ],
)
def test_passwords_with_the_users_mobile_or_name_are_refused(password: str) -> None:
    with pytest.raises(AppError) as personal:
        check_password_policy(password, name="Ravi Kumar", mobile="+919000000101")
    assert personal.value.code == "PASSWORD_TOO_PERSONAL"
    assert password not in personal.value.message


def test_unrelated_passwords_pass_the_personal_check() -> None:
    check_password_policy("Kite-river-lamp-0001", name="Ravi Kumar", mobile="+919000000101")
    # Short name parts (under 3 letters) are not treated as the name on their own.
    check_password_policy("Al-stone-bell-0001", name="Al Shan", mobile="+919000000101")
    # Part of the mobile number is not the mobile number.
    check_password_policy("Kite-9000000-lamp", name="Ravi Kumar", mobile="+919000000101")


def test_the_personal_check_needs_the_user_details() -> None:
    check_password_policy("Ravi@2026xyz!")  # nothing to compare against
