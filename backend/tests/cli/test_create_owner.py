"""The first-run command creates the single owner from terminal prompts (no default password)."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.cli.create_owner import OwnerAlreadyExistsError, collect_and_create
from app.core.audit import AuditLog
from app.core.errors import AppError
from app.modules.users.models import User


def _run(session: Session, text_answers: list[str], secret_answers: list[str]) -> User:
    texts = iter(text_answers)
    secrets = iter(secret_answers)
    return collect_and_create(
        session,
        ask=lambda _prompt: next(texts),
        ask_secret=lambda _prompt: next(secrets),
        say=lambda _message: None,
    )


@pytest.fixture
def empty_users(owner_db: Session) -> Session:
    owner_db.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    return owner_db


def test_creates_the_owner(empty_users: Session) -> None:
    user = _run(
        empty_users,
        ["Test Owner", "9000000001", "owner@example.test"],
        ["Kite-river-lamp-0001", "Kite-river-lamp-0001"],
    )
    assert user.role == "owner"
    assert user.mobile == "+919000000001"
    assert user.password_hash.startswith("$argon2id$")
    assert user.must_change_password is False
    assert user.totp_secret is None  # enrolment happens at the first browser sign-in
    actions = empty_users.scalars(select(AuditLog.action)).all()
    assert "user.owner_created" in actions


def test_refuses_a_second_owner(empty_users: Session) -> None:
    answers = ["Test Owner", "9000000001", ""]
    _run(empty_users, answers, ["Kite-river-lamp-0001", "Kite-river-lamp-0001"])
    with pytest.raises(OwnerAlreadyExistsError):
        _run(
            empty_users,
            ["Test Owner 2", "9000000002", ""],
            ["Kite-river-lamp-0002", "Kite-river-lamp-0002"],
        )
    assert empty_users.scalar(select(func.count()).select_from(User)) == 1


def test_mismatched_passwords_are_asked_again(empty_users: Session) -> None:
    user = _run(
        empty_users,
        ["Test Owner", "9000000001", ""],
        ["Kite-river-lamp-0001", "Typo-pass-00001", "Kite-river-lamp-0001", "Kite-river-lamp-0001"],
    )
    assert user.email is None


def test_weak_passwords_are_asked_again(empty_users: Session) -> None:
    user = _run(
        empty_users,
        ["Test Owner", "9000000001", ""],
        [
            "short",
            "short",
            "1234567890",
            "1234567890",
            "Kite-river-lamp-0001",
            "Kite-river-lamp-0001",
        ],
    )
    assert user.role == "owner"


def test_an_invalid_mobile_is_refused(empty_users: Session) -> None:
    with pytest.raises(AppError):
        _run(empty_users, ["Test Owner", "12345", ""], ["Kite-river-lamp-0001"] * 2)


def test_a_password_with_the_owners_name_or_mobile_is_asked_again(empty_users: Session) -> None:
    messages: list[str] = []
    texts = iter(["Test Owner Lakshmi", "9000000001", ""])
    secrets = iter(
        [
            "Lakshmi-2026-key",
            "Lakshmi-2026-key",
            "Key-9000000001-x",
            "Key-9000000001-x",
            "Kite-river-lamp-0001",
            "Kite-river-lamp-0001",
        ]
    )
    user = collect_and_create(
        empty_users,
        ask=lambda _prompt: next(texts),
        ask_secret=lambda _prompt: next(secrets),
        say=messages.append,
    )
    assert user.role == "owner"
    assert messages.count("Do not use your name or mobile number in your password.") == 2
