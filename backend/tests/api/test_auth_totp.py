"""Owner 2-step sign-in with TOTP, enrolment at first sign-in, and recovery codes."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.auth.models import RecoveryCode
from app.modules.users.models import User
from tests.api.conftest import FakeClock, OwnerContext, StaffFactory
from tests.api.helpers import (
    API,
    OWNER_MOBILE,
    OWNER_PASSWORD,
    REFRESH_COOKIE,
    STAFF_PASSWORD,
    bearer,
    error_code,
    login,
    make_owner,
    owner_challenge,
    totp_code,
)


def test_owner_login_without_a_totp_code_is_refused(
    api: TestClient, owner: OwnerContext, clock: FakeClock
) -> None:
    clock.advance(seconds=30)
    response = login(api, owner.login, owner.password)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "totp_required"
    assert "access_token" not in body
    assert response.cookies.get(REFRESH_COOKIE) is None

    # The challenge is not an access token.
    challenge = body["challenge_token"]
    assert api.get(f"{API}/settings/current", headers=bearer(challenge)).status_code == 401

    no_code = api.post(f"{API}/auth/totp", json={"challenge_token": challenge})
    assert no_code.status_code == 422
    wrong = api.post(f"{API}/auth/totp", json={"challenge_token": challenge, "code": "123456"})
    assert wrong.status_code == 401
    assert error_code(wrong) == "TOTP_INVALID"


def test_owner_login_with_a_valid_code_succeeds(
    api: TestClient, owner: OwnerContext, clock: FakeClock
) -> None:
    clock.advance(seconds=30)
    challenge = owner_challenge(api, owner.login, owner.password)
    response = api.post(
        f"{API}/auth/totp",
        json={"challenge_token": challenge, "code": totp_code(owner.totp_secret, clock)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["user"]["role"] == "owner"
    assert "users.manage" in body["user"]["permissions"]
    assert response.cookies.get(REFRESH_COOKIE)
    assert (
        api.get(f"{API}/settings/current", headers=bearer(body["access_token"])).status_code == 200
    )


def test_a_reused_code_within_the_same_window_is_refused(
    api: TestClient, owner: OwnerContext, clock: FakeClock
) -> None:
    clock.advance(seconds=30)
    code = totp_code(owner.totp_secret, clock)
    first = owner_challenge(api, owner.login, owner.password)
    assert (
        api.post(f"{API}/auth/totp", json={"challenge_token": first, "code": code}).status_code
        == 200
    )

    second = owner_challenge(api, owner.login, owner.password)
    reused = api.post(f"{API}/auth/totp", json={"challenge_token": second, "code": code})
    assert reused.status_code == 401
    assert error_code(reused) == "TOTP_INVALID"


def test_the_code_from_enrolment_cannot_be_replayed(
    api: TestClient, owner: OwnerContext, clock: FakeClock
) -> None:
    # Same 30-second window as the confirm step in the fixture: that code is spent.
    challenge = owner_challenge(api, owner.login, owner.password)
    response = api.post(
        f"{API}/auth/totp",
        json={"challenge_token": challenge, "code": totp_code(owner.totp_secret, clock)},
    )
    assert response.status_code == 401


def test_the_challenge_expires_after_5_minutes(
    api: TestClient, owner: OwnerContext, clock: FakeClock
) -> None:
    clock.advance(seconds=30)
    challenge = owner_challenge(api, owner.login, owner.password)
    clock.advance(minutes=5, seconds=1)
    response = api.post(
        f"{API}/auth/totp",
        json={"challenge_token": challenge, "code": totp_code(owner.totp_secret, clock)},
    )
    assert response.status_code == 401
    assert error_code(response) == "CHALLENGE_INVALID"


def test_first_sign_in_requires_enrolment(
    api: TestClient, app_engine: Engine, clock: FakeClock, settings_v1: None
) -> None:
    owner_id = make_owner(app_engine)
    response = login(api, OWNER_MOBILE, OWNER_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "totp_setup_required"
    assert "access_token" not in body
    challenge = body["challenge_token"]

    # The setup challenge allows only TOTP setup and confirmation.
    assert api.get(f"{API}/settings/current", headers=bearer(challenge)).status_code == 401
    not_yet = api.post(f"{API}/auth/totp", json={"challenge_token": challenge, "code": "123456"})
    assert not_yet.status_code == 401
    assert error_code(not_yet) == "CHALLENGE_INVALID"

    setup = api.post(f"{API}/auth/totp/setup", json={"challenge_token": challenge})
    assert setup.status_code == 200, setup.text
    data = setup.json()
    secret = data["secret"]
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert "<svg" in data["qr_svg"]

    wrong = api.post(
        f"{API}/auth/totp/confirm", json={"challenge_token": challenge, "code": "000000"}
    )
    assert wrong.status_code == 401

    confirm = api.post(
        f"{API}/auth/totp/confirm",
        json={"challenge_token": challenge, "code": totp_code(secret, clock)},
    )
    assert confirm.status_code == 200, confirm.text
    result = confirm.json()
    assert result["status"] == "ok"
    assert len(result["recovery_codes"]) == 10
    assert len(set(result["recovery_codes"])) == 10
    assert confirm.cookies.get(REFRESH_COOKIE)

    with Session(app_engine) as session:
        user = session.get(User, owner_id)
        assert user is not None
        assert user.totp_secret is not None
        assert secret not in user.totp_secret  # encrypted at rest
        assert user.totp_pending_secret is None
        assert user.totp_confirmed_at is not None
        hashes = session.scalars(
            select(RecoveryCode.code_hash).where(RecoveryCode.user_id == owner_id)
        ).all()
    assert len(hashes) == 10
    for code in result["recovery_codes"]:
        assert all(code not in stored for stored in hashes)  # stored hashed

    # Now the owner is enrolled: setup with a fresh challenge is refused.
    clock.advance(seconds=30)
    later = owner_challenge(api, OWNER_MOBILE, OWNER_PASSWORD)
    again = api.post(f"{API}/auth/totp/setup", json={"challenge_token": later})
    assert again.status_code == 401
    assert error_code(again) == "CHALLENGE_INVALID"


def test_setup_secret_changes_until_confirmed(
    api: TestClient, app_engine: Engine, settings_v1: None
) -> None:
    make_owner(app_engine)
    challenge = login(api, OWNER_MOBILE, OWNER_PASSWORD).json()["challenge_token"]
    first = api.post(f"{API}/auth/totp/setup", json={"challenge_token": challenge}).json()
    second = api.post(f"{API}/auth/totp/setup", json={"challenge_token": challenge}).json()
    assert first["secret"] != second["secret"]


def test_a_recovery_code_works_once(api: TestClient, owner: OwnerContext, clock: FakeClock) -> None:
    code = owner.recovery_codes[0]
    challenge = owner_challenge(api, owner.login, owner.password)
    used = api.post(f"{API}/auth/totp", json={"challenge_token": challenge, "recovery_code": code})
    assert used.status_code == 200, used.text

    challenge = owner_challenge(api, owner.login, owner.password)
    again = api.post(f"{API}/auth/totp", json={"challenge_token": challenge, "recovery_code": code})
    assert again.status_code == 401
    assert error_code(again) == "TOTP_INVALID"


def test_staff_get_no_totp_step(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    response = login(api, "9000000101", STAFF_PASSWORD)
    assert response.json()["status"] == "ok"
    assert response.json()["user"]["role"] == "staff"
