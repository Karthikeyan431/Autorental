"""Every request re-checks is_active; deactivation and password resets revoke sessions."""

from fastapi.testclient import TestClient

from tests.api.conftest import OwnerContext, StaffFactory
from tests.api.helpers import (
    API,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    STAFF_PASSWORD,
    bearer,
    error_code,
    login,
    refresh,
    staff_token,
)


def test_deactivated_staff_access_token_gets_401_on_the_next_request(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    token = staff_token(api, "9000000101")
    assert api.get(f"{API}/settings/current", headers=bearer(token)).status_code == 200

    response = api.post(f"{API}/users/{staff_id}/deactivate", headers=bearer(owner.token), json={})
    assert response.status_code == 200, response.text

    after = api.get(f"{API}/settings/current", headers=bearer(token))
    assert after.status_code == 401


def test_deactivation_revokes_refresh_tokens(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    signed_in = login(api, "9000000101", STAFF_PASSWORD)
    refresh_value = signed_in.cookies.get(REFRESH_COOKIE)
    csrf = signed_in.cookies.get(CSRF_COOKIE)
    assert refresh_value and csrf

    api.post(f"{API}/users/{staff_id}/deactivate", headers=bearer(owner.token), json={})
    assert refresh(api, refresh_value, csrf).status_code == 401


def test_reactivated_staff_can_sign_in_again(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    api.post(f"{API}/users/{staff_id}/deactivate", headers=bearer(owner.token), json={})
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 401
    response = api.post(f"{API}/users/{staff_id}/reactivate", headers=bearer(owner.token))
    assert response.status_code == 200, response.text
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 200


def test_password_reset_forces_a_change_at_next_login(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    old_token = staff_token(api, "9000000101")

    reset = api.post(f"{API}/users/{staff_id}/reset-password", headers=bearer(owner.token))
    assert reset.status_code == 200, reset.text
    temporary = reset.json()["temporary_password"]
    assert len(temporary) >= 12

    # The reset signs the staff member out everywhere.
    assert api.get(f"{API}/settings/current", headers=bearer(old_token)).status_code == 401
    assert login(api, "9000000101", STAFF_PASSWORD).status_code == 401

    signed_in = login(api, "9000000101", temporary)
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["must_change_password"] is True
    token = signed_in.json()["access_token"]

    blocked = api.get(f"{API}/settings/current", headers=bearer(token))
    assert blocked.status_code == 403
    assert error_code(blocked) == "PASSWORD_CHANGE_REQUIRED"

    changed = api.post(
        f"{API}/auth/change-password",
        headers=bearer(token),
        json={"current_password": temporary, "new_password": "Brand-new-pass-0002"},
    )
    assert changed.status_code == 204, changed.text
    assert api.get(f"{API}/settings/current", headers=bearer(token)).status_code == 200
    assert (
        login(api, "9000000101", "Brand-new-pass-0002").json()["user"]["must_change_password"]
        is False
    )


def test_change_password_enforces_the_policy(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    token = staff_token(api, "9000000101")

    def change(current: str, new: str) -> tuple[int, str]:
        response = api.post(
            f"{API}/auth/change-password",
            headers=bearer(token),
            json={"current_password": current, "new_password": new},
        )
        return response.status_code, error_code(response) if response.status_code >= 400 else ""

    assert change(STAFF_PASSWORD, "short-1") == (422, "PASSWORD_TOO_SHORT")
    assert change(STAFF_PASSWORD, "1234567890") == (422, "PASSWORD_TOO_COMMON")
    assert change(STAFF_PASSWORD, "Charlie123") == (422, "PASSWORD_TOO_COMMON")  # any case
    assert change("Wrong-current-pass", "Brand-new-pass-0002") == (
        409,
        "CURRENT_PASSWORD_INCORRECT",
    )
    assert change(STAFF_PASSWORD, STAFF_PASSWORD) == (409, "PASSWORD_UNCHANGED")
    assert change(STAFF_PASSWORD, "Brand-new-pass-0002") == (204, "")


def test_changing_the_password_signs_out_other_sessions(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    phone = staff_token(api, "9000000101")
    laptop = staff_token(api, "9000000101")
    api.post(
        f"{API}/auth/change-password",
        headers=bearer(laptop),
        json={"current_password": STAFF_PASSWORD, "new_password": "Brand-new-pass-0002"},
    )
    assert api.get(f"{API}/settings/current", headers=bearer(laptop)).status_code == 200
    assert api.get(f"{API}/settings/current", headers=bearer(phone)).status_code == 401
