"""Rule 16: up to `staff_limit` active staff (default 10); only the owner raises it."""

from fastapi.testclient import TestClient

from tests.api.conftest import OwnerContext, StaffFactory
from tests.api.helpers import API, bearer, error_code


def _create(api: TestClient, token: str, mobile: str) -> tuple[int, str]:
    response = api.post(
        f"{API}/users",
        headers=bearer(token),
        json={"name": f"Test Staff {mobile[-3:]}", "mobile": mobile},
    )
    return response.status_code, error_code(response) if response.status_code >= 400 else ""


def test_the_11th_active_staff_is_refused_until_the_limit_is_raised(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    for _ in range(10):
        staff_factory()

    assert _create(api, owner.token, "9000000211") == (409, "STAFF_LIMIT_REACHED")

    raised = api.post(f"{API}/settings", headers=bearer(owner.token), json={"staff_limit": 11})
    assert raised.status_code == 201, raised.text
    assert raised.json()["staff_limit"] == 11

    assert _create(api, owner.token, "9000000211") == (201, "")
    assert _create(api, owner.token, "9000000212") == (409, "STAFF_LIMIT_REACHED")


def test_reactivating_beyond_the_limit_is_refused(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    inactive_id = staff_factory(is_active=False)
    for _ in range(10):
        staff_factory()

    response = api.post(f"{API}/users/{inactive_id}/reactivate", headers=bearer(owner.token))
    assert response.status_code == 409
    assert error_code(response) == "STAFF_LIMIT_REACHED"


def test_inactive_staff_do_not_count(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    ids = [staff_factory() for _ in range(10)]
    api.post(f"{API}/users/{ids[0]}/deactivate", headers=bearer(owner.token), json={})
    assert _create(api, owner.token, "9000000211") == (201, "")


def test_the_owner_does_not_count_toward_the_limit(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    for _ in range(9):
        staff_factory()
    assert _create(api, owner.token, "9000000211") == (201, "")


def test_staff_cannot_raise_the_limit(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    token = api.post(
        f"{API}/auth/login", json={"login": "9000000101", "password": "Plum-stone-bell-0001"}
    ).json()["access_token"]
    response = api.post(f"{API}/settings", headers=bearer(token), json={"staff_limit": 50})
    assert response.status_code == 403
