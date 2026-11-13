"""Settings API: a new version on each change, owner only; everyone signed in can read."""

from fastapi.testclient import TestClient

from tests.api.conftest import OwnerContext, StaffFactory
from tests.api.helpers import API, bearer, staff_token


def test_each_change_creates_a_new_version(api: TestClient, owner: OwnerContext) -> None:
    before = api.get(f"{API}/settings/current", headers=bearer(owner.token)).json()
    response = api.post(
        f"{API}/settings",
        headers=bearer(owner.token),
        json={"rent_due_time": "09:30:00", "reason": "Client asked for 9:30"},
    )
    assert response.status_code == 201, response.text
    after = response.json()
    assert after["id"] != before["id"]
    assert after["rent_due_time"] == "09:30:00"
    assert after["business_name"] == before["business_name"]  # copied forward

    versions = api.get(f"{API}/settings/versions", headers=bearer(owner.token)).json()
    assert versions["total"] == 2
    assert versions["items"][0]["id"] == after["id"]  # newest first
    assert versions["items"][0]["created_by"] == owner.id


def test_staff_can_read_but_not_change_settings(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    token = staff_token(api, "9000000101")
    assert api.get(f"{API}/settings/current", headers=bearer(token)).status_code == 200
    assert api.get(f"{API}/settings/versions", headers=bearer(token)).status_code == 200
    assert (
        api.post(f"{API}/settings", headers=bearer(token), json={"staff_limit": 12}).status_code
        == 403
    )


def test_invalid_settings_are_refused(api: TestClient, owner: OwnerContext) -> None:
    for body in ({"staff_limit": 0}, {"weekly_pay_day": 8}, {"weekly_mdr_warning_paise": 1.5}):
        response = api.post(f"{API}/settings", headers=bearer(owner.token), json=body)
        assert response.status_code == 422, body


def test_an_empty_change_is_refused(api: TestClient, owner: OwnerContext) -> None:
    response = api.post(f"{API}/settings", headers=bearer(owner.token), json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_SETTINGS_CHANGED"
