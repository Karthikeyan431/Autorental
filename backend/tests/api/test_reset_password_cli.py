"""Account recovery from the server shell: python -m app.cli.reset_password.

Anyone with shell access to the server can already read the database, so this command works in
every APP_ENV, including production. It sets a new password (typed twice, hidden, normal
policy), clears the lockout, signs the user out everywhere, forces a password change at the
next sign-in and, with --reset-totp, clears the owner's 2-step setup. Audit actor: system:cli.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.cli import reset_password as cli
from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import verify_password
from app.modules.auth.models import AuthSession, RecoveryCode
from app.modules.users.models import User
from tests.api.conftest import FakeClock, OwnerContext, StaffFactory
from tests.api.helpers import (
    API,
    OWNER_MOBILE,
    bearer,
    login,
    staff_token,
    totp_code,
)

NEW_PASSWORD = "Harbour-maple-tin-0042"
STAFF_MOBILE = "9000000401"


def _run(
    engine: Engine,
    login_id: str,
    secrets: list[str],
    *,
    reset_totp: bool = False,
    messages: list[str] | None = None,
) -> int:
    answers = iter(secrets)
    with Session(engine) as session, session.begin():
        user = cli.collect_and_reset(
            session,
            login_id=login_id,
            ask_secret=lambda _prompt: next(answers),
            say=(messages.append if messages is not None else lambda _m: None),
            reset_totp=reset_totp,
        )
        return user.id


def _user(engine: Engine, user_id: int) -> User:
    with Session(engine, expire_on_commit=False) as session:
        user = session.get(User, user_id)
        assert user is not None
        return user


def _live_sessions(engine: Engine, user_id: int) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            )
            or 0
        )


def test_sets_the_password_and_forces_a_change_at_next_sign_in(
    api: TestClient, owner: OwnerContext, app_engine: Engine
) -> None:
    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD])

    user = _user(app_engine, owner.id)
    assert verify_password(user.password_hash, NEW_PASSWORD)
    assert not verify_password(user.password_hash, owner.password)
    assert user.must_change_password is True


def test_the_user_can_be_found_by_email(owner: OwnerContext, app_engine: Engine) -> None:
    user_id = _run(app_engine, "  OWNER@example.test ", [NEW_PASSWORD, NEW_PASSWORD])
    assert user_id == owner.id


def test_clears_the_lockout(
    api: TestClient, owner: OwnerContext, app_engine: Engine, clock: FakeClock
) -> None:
    with Session(app_engine) as session, session.begin():
        user = session.get(User, owner.id)
        assert user is not None
        user.failed_logins = 7
        user.locked_until = clock.now() + timedelta(minutes=30)

    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD])

    user = _user(app_engine, owner.id)
    assert user.failed_logins == 0
    assert user.locked_until is None
    response = login(api, OWNER_MOBILE, NEW_PASSWORD)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "totp_required"


def test_signs_the_user_out_everywhere(
    api: TestClient, owner: OwnerContext, app_engine: Engine
) -> None:
    assert _live_sessions(app_engine, owner.id) >= 1
    assert api.get(f"{API}/drivers", headers=bearer(owner.token)).status_code == 200

    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD])

    assert _live_sessions(app_engine, owner.id) == 0
    response = api.get(f"{API}/drivers", headers=bearer(owner.token))
    assert response.status_code == 401


def test_keeps_the_authenticator_unless_asked(
    api: TestClient, owner: OwnerContext, app_engine: Engine, clock: FakeClock
) -> None:
    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD])

    user = _user(app_engine, owner.id)
    assert user.totp_secret is not None
    clock.advance(seconds=30)  # a TOTP code is accepted once; use the next time step
    challenge = login(api, OWNER_MOBILE, NEW_PASSWORD).json()
    assert challenge["status"] == "totp_required"
    done = api.post(
        f"{API}/auth/totp",
        json={
            "challenge_token": challenge["challenge_token"],
            "code": totp_code(owner.totp_secret, clock),
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["user"]["must_change_password"] is True


def test_reset_totp_clears_the_owners_two_step_setup(
    api: TestClient, owner: OwnerContext, app_engine: Engine
) -> None:
    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD], reset_totp=True)

    user = _user(app_engine, owner.id)
    assert user.totp_secret is None
    assert user.totp_pending_secret is None
    assert user.totp_confirmed_at is None
    assert user.totp_last_step is None
    with Session(app_engine) as session:
        codes = session.scalar(
            select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == owner.id)
        )
    assert codes == 0
    # The next sign-in sets up a new authenticator app.
    response = login(api, OWNER_MOBILE, NEW_PASSWORD)
    assert response.json()["status"] == "totp_setup_required"


def test_reset_totp_is_refused_for_staff(staff_factory: StaffFactory, app_engine: Engine) -> None:
    staff_id = staff_factory(name="Test Staff 401", mobile=STAFF_MOBILE)
    before = _user(app_engine, staff_id).password_hash
    with pytest.raises(AppError) as caught:
        _run(app_engine, STAFF_MOBILE, [NEW_PASSWORD, NEW_PASSWORD], reset_totp=True)
    assert caught.value.code == "TOTP_RESET_OWNER_ONLY"
    assert _user(app_engine, staff_id).password_hash == before


def test_works_for_staff(api: TestClient, staff_factory: StaffFactory, app_engine: Engine) -> None:
    staff_id = staff_factory(name="Test Staff 401", mobile=STAFF_MOBILE)
    token = staff_token(api, STAFF_MOBILE)

    _run(app_engine, STAFF_MOBILE, [NEW_PASSWORD, NEW_PASSWORD])

    assert api.get(f"{API}/drivers", headers=bearer(token)).status_code == 401
    response = login(api, STAFF_MOBILE, NEW_PASSWORD)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["must_change_password"] is True
    assert _user(app_engine, staff_id).must_change_password is True


def test_an_unknown_user_is_refused(owner: OwnerContext, app_engine: Engine) -> None:
    with pytest.raises(AppError) as caught:
        _run(app_engine, "9000000999", [NEW_PASSWORD, NEW_PASSWORD])
    assert caught.value.code == "USER_NOT_FOUND"
    with pytest.raises(AppError):
        _run(app_engine, "not a login", [NEW_PASSWORD, NEW_PASSWORD])


def test_weak_and_mismatched_passwords_are_asked_again(
    owner: OwnerContext, app_engine: Engine
) -> None:
    messages: list[str] = []
    _run(
        app_engine,
        OWNER_MOBILE,
        [
            "short",
            "short",
            "1234567890",
            "1234567890",
            "Key-9000000001-x",
            "Key-9000000001-x",
            NEW_PASSWORD,
            "Typo-" + NEW_PASSWORD,
            NEW_PASSWORD,
            NEW_PASSWORD,
        ],
        messages=messages,
    )
    assert "Use at least 10 characters." in messages
    assert "This password is too common. Choose a less predictable one." in messages
    assert "Do not use your name or mobile number in your password." in messages
    assert "The two passwords do not match. Try again." in messages
    assert verify_password(_user(app_engine, owner.id).password_hash, NEW_PASSWORD)


def test_writes_an_audit_entry_without_secrets(owner: OwnerContext, app_engine: Engine) -> None:
    _run(app_engine, OWNER_MOBILE, [NEW_PASSWORD, NEW_PASSWORD], reset_totp=True)

    with Session(app_engine) as session:
        entry = session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "user.password_reset_cli")
            .order_by(AuditLog.id.desc())
        ).first()
    assert entry is not None
    assert entry.entity_type == "user"
    assert entry.entity_id == owner.id
    assert entry.actor_id is None
    assert entry.after == {
        "actor": "system:cli",
        "forced_change": True,
        "lockout_cleared": True,
        "sessions_revoked": True,
        "two_step_cleared": True,
    }
    stored = f"{entry.before} {entry.after} {entry.reason}"
    assert NEW_PASSWORD not in stored
    assert "9000000001" not in stored
    assert "example.test" not in stored


@pytest.fixture
def production_settings(test_settings: Settings, clean_db: None) -> Iterator[Settings]:
    yield test_settings.model_copy(update={"APP_ENV": "production"})


def test_main_works_in_production(
    monkeypatch: pytest.MonkeyPatch,
    owner: OwnerContext,
    app_engine: Engine,
    production_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: production_settings)
    monkeypatch.setattr("builtins.input", lambda _prompt: OWNER_MOBILE)
    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    assert cli.main([]) == 0

    assert verify_password(_user(app_engine, owner.id).password_hash, NEW_PASSWORD)
    out = capsys.readouterr()
    assert NEW_PASSWORD not in out.out + out.err
    assert "9000000001" not in out.out + out.err


def test_main_reports_an_unknown_user_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    owner: OwnerContext,
    app_engine: Engine,
    test_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _user(app_engine, owner.id).password_hash
    monkeypatch.setattr(cli, "get_settings", lambda: test_settings)
    monkeypatch.setattr("builtins.input", lambda _prompt: "9000000999")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: NEW_PASSWORD)

    assert cli.main(["--reset-totp"]) == 1

    assert _user(app_engine, owner.id).password_hash == before
    assert "No user has that mobile number or email." in capsys.readouterr().err


def test_main_accepts_the_reset_totp_flag(
    monkeypatch: pytest.MonkeyPatch,
    owner: OwnerContext,
    app_engine: Engine,
    test_settings: Settings,
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: test_settings)
    monkeypatch.setattr("builtins.input", lambda _prompt: OWNER_MOBILE)
    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    assert cli.main(["--reset-totp"]) == 0

    assert _user(app_engine, owner.id).totp_secret is None
