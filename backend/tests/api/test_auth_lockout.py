"""Lockout after 5 failures for 15 minutes, and the per-IP throttle (docs/security.md)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.users.models import User
from tests.api.conftest import ClientFactory, FakeClock, OwnerContext, StaffFactory
from tests.api.helpers import (
    API,
    STAFF_PASSWORD,
    error_code,
    login,
    owner_challenge,
)

LOCKED_MESSAGE = "Too many attempts. Try again in 15 minutes."


def _lock(api: TestClient, mobile: str) -> None:
    for _ in range(5):
        response = login(api, mobile, "Wrong-password-000")
        assert response.status_code == 401
        assert error_code(response) == "INVALID_CREDENTIALS"


def test_five_wrong_passwords_lock_the_account(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    _lock(api, "9000000101")

    response = login(api, "9000000101", STAFF_PASSWORD)
    assert response.status_code == 429
    assert error_code(response) == "ACCOUNT_LOCKED"
    assert response.json()["error"]["message"] == LOCKED_MESSAGE


def test_correct_password_works_after_15_minutes(
    api: TestClient, staff_factory: StaffFactory, clock: FakeClock
) -> None:
    staff_factory(mobile="9000000101")
    _lock(api, "9000000101")

    clock.advance(minutes=14, seconds=59)
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 429

    clock.advance(seconds=1)
    response = login(api, "9000000101", STAFF_PASSWORD)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


def test_four_failures_then_success_resets_the_count(
    api: TestClient, staff_factory: StaffFactory, app_engine: Engine
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    for _ in range(4):
        assert login(api, "9000000101", "Wrong-password-000").status_code == 401
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 200
    for _ in range(4):
        assert login(api, "9000000101", "Wrong-password-000").status_code == 401
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 200

    with Session(app_engine) as session:
        user = session.get(User, staff_id)
        assert user is not None
        assert user.locked_until is None
        assert user.failed_logins == 0


def test_ip_throttle_after_20_failures_in_15_minutes(
    make_client: ClientFactory, staff_factory: StaffFactory, clock: FakeClock
) -> None:
    staff_factory(mobile="9000000101")
    noisy = make_client("203.0.113.7")
    for i in range(20):
        response = login(noisy, f"9000009{i:03d}", "Wrong-password-000")  # unknown accounts
        assert response.status_code == 401, i

    throttled = login(noisy, "9000000101", STAFF_PASSWORD)
    assert throttled.status_code == 429
    assert error_code(throttled) == "IP_THROTTLED"

    # Another address is not affected, and the account itself is not locked.
    assert login(make_client("203.0.113.8"), "9000000101", STAFF_PASSWORD).status_code == 200

    clock.advance(minutes=15, seconds=1)
    assert login(noisy, "9000000101", STAFF_PASSWORD).status_code == 200


def test_failed_totp_codes_count_toward_the_lockout(api: TestClient, owner: OwnerContext) -> None:
    for _ in range(5):
        challenge = owner_challenge(api, owner.login, owner.password)
        response = api.post(
            f"{API}/auth/totp", json={"challenge_token": challenge, "code": "000000"}
        )
        assert response.status_code == 401
        assert error_code(response) == "TOTP_INVALID"

    locked = login(api, owner.login, owner.password)
    assert locked.status_code == 429
    assert error_code(locked) == "ACCOUNT_LOCKED"


def test_login_accepts_mobile_formats_and_email(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101", email="Staff101@Example.Test")
    for login_id in (
        "9000000101",
        "+919000000101",
        "+91 90000 00101",
        "staff101@example.test",
        "STAFF101@EXAMPLE.TEST",
    ):
        response = login(api, login_id, STAFF_PASSWORD)
        assert response.status_code == 200, login_id


def test_unknown_and_inactive_accounts_get_the_same_answer(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101", is_active=False)
    inactive = login(api, "9000000101", STAFF_PASSWORD)
    unknown = login(api, "9000000999", STAFF_PASSWORD)
    assert inactive.status_code == unknown.status_code == 401
    assert error_code(inactive) == error_code(unknown) == "INVALID_CREDENTIALS"
    assert inactive.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_a_failed_login_is_committed_even_though_the_request_is_refused(
    api: TestClient, staff_factory: StaffFactory, app_engine: Engine
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    login(api, "9000000101", "Wrong-password-000")
    with Session(app_engine) as session:
        failed = session.scalar(select(User.failed_logins).where(User.id == staff_id))
    assert failed == 1
