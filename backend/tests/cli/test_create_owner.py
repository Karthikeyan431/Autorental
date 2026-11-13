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
        ["Owner-test-pass-0001", "Owner-test-pass-0001"],
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
    _run(empty_users, answers, ["Owner-test-pass-0001", "Owner-test-pass-0001"])
    with pytest.raises(OwnerAlreadyExistsError):
        _run(
            empty_users,
            ["Test Owner 2", "9000000002", ""],
            ["Owner-test-pass-0002", "Owner-test-pass-0002"],
        )
    assert empty_users.scalar(select(func.count()).select_from(User)) == 1


def test_mismatched_passwords_are_asked_again(empty_users: Session) -> None:
    user = _run(
        empty_users,
        ["Test Owner", "9000000001", ""],
        ["Owner-test-pass-0001", "Typo-pass-00001", "Owner-test-pass-0001", "Owner-test-pass-0001"],
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
            "Owner-test-pass-0001",
            "Owner-test-pass-0001",
        ],
    )
    assert user.role == "owner"


def test_an_invalid_mobile_is_refused(empty_users: Session) -> None:
    with pytest.raises(AppError):
        _run(empty_users, ["Test Owner", "12345", ""], ["Owner-test-pass-0001"] * 2)
