"""Refresh token rotation, reuse detection, CSRF and logout (docs/security.md)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from tests.api.conftest import FakeClock, StaffFactory
from tests.api.helpers import (
    API,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    STAFF_PASSWORD,
    bearer,
    error_code,
    login,
    refresh,
)


def _sign_in(api: TestClient) -> tuple[str, str, str]:
    response = login(api, "9000000101", STAFF_PASSWORD)
    assert response.status_code == 200, response.text
    refresh_value = response.cookies.get(REFRESH_COOKIE)
    csrf = response.cookies.get(CSRF_COOKIE)
    assert refresh_value and csrf
    return str(response.json()["access_token"]), refresh_value, csrf


def test_login_sets_a_strict_http_only_secure_refresh_cookie(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    response = login(api, "9000000101", STAFF_PASSWORD)
    set_cookies = response.headers.get_list("set-cookie")
    refresh_header = next(c for c in set_cookies if c.startswith(f"{REFRESH_COOKIE}="))
    lowered = refresh_header.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=strict" in lowered
    assert "path=/api/v1/auth" in lowered
    csrf_header = next(c for c in set_cookies if c.startswith(f"{CSRF_COOKIE}="))
    assert "httponly" not in csrf_header.lower()  # the page reads it for the double submit
    assert "secure" in csrf_header.lower()
    assert response.json()["expires_in"] == 15 * 60


def test_refresh_rotates_the_token(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    _, old_refresh, csrf = _sign_in(api)

    response = refresh(api, old_refresh, csrf)
    assert response.status_code == 200, response.text
    new_refresh = response.cookies.get(REFRESH_COOKIE)
    assert new_refresh and new_refresh != old_refresh
    new_access = response.json()["access_token"]
    assert api.get(f"{API}/settings/current", headers=bearer(new_access)).status_code == 200


def test_reusing_an_old_refresh_token_revokes_the_whole_family(
    api: TestClient, staff_factory: StaffFactory, app_engine: Engine
) -> None:
    staff_factory(mobile="9000000101")
    _, first, csrf = _sign_in(api)
    rotated = refresh(api, first, csrf)
    assert rotated.status_code == 200
    second = rotated.cookies.get(REFRESH_COOKIE)
    second_csrf = rotated.cookies.get(CSRF_COOKIE)
    assert second and second_csrf
    second_access = rotated.json()["access_token"]

    reuse = refresh(api, first, csrf)
    assert reuse.status_code == 401
    assert error_code(reuse) == "REFRESH_REUSED"

    # Every token in the family is now dead, including the newest one and its access token.
    assert refresh(api, second, second_csrf).status_code == 401
    assert api.get(f"{API}/settings/current", headers=bearer(second_access)).status_code == 401

    with Session(app_engine) as session:
        actions = session.scalars(select(AuditLog.action)).all()
    assert "auth.refresh_reuse_detected" in actions


def test_refresh_needs_the_matching_csrf_header(
    api: TestClient, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101")
    _, refresh_value, csrf = _sign_in(api)

    missing = refresh(api, refresh_value, None)
    assert missing.status_code == 403
    assert error_code(missing) == "CSRF_FAILED"

    api.cookies.clear()
    wrong = api.post(
        f"{API}/auth/refresh",
        headers={
            "Cookie": f"{REFRESH_COOKIE}={refresh_value}; {CSRF_COOKIE}={csrf}",
            "X-CSRF-Token": "not-the-token",
        },
    )
    assert wrong.status_code == 403
    # A refused CSRF check does not burn the refresh token.
    assert refresh(api, refresh_value, csrf).status_code == 200


def test_unknown_refresh_token_is_refused(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    response = refresh(api, "made-up-token", "made-up-csrf")
    assert response.status_code == 401
    assert error_code(response) == "REFRESH_INVALID"


def test_refresh_expires_after_7_days(
    api: TestClient, staff_factory: StaffFactory, clock: FakeClock
) -> None:
    staff_factory(mobile="9000000101")
    _, refresh_value, csrf = _sign_in(api)
    clock.advance(days=7, minutes=1)
    response = refresh(api, refresh_value, csrf)
    assert response.status_code == 401
    assert error_code(response) == "REFRESH_INVALID"


def test_access_token_expires_after_15_minutes(
    api: TestClient, staff_factory: StaffFactory, clock: FakeClock
) -> None:
    staff_factory(mobile="9000000101")
    access, _, _ = _sign_in(api)
    clock.advance(minutes=15, seconds=1)
    response = api.get(f"{API}/settings/current", headers=bearer(access))
    assert response.status_code == 401


def test_logout_revokes_the_session(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    access, refresh_value, csrf = _sign_in(api)

    response = api.post(f"{API}/auth/logout", headers=bearer(access))
    assert response.status_code == 204

    assert api.get(f"{API}/settings/current", headers=bearer(access)).status_code == 401
    assert refresh(api, refresh_value, csrf).status_code == 401


def test_logout_leaves_other_sessions_alone(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(mobile="9000000101")
    phone_access, _, _ = _sign_in(api)
    laptop_access, _, _ = _sign_in(api)
    api.post(f"{API}/auth/logout", headers=bearer(phone_access))
    assert api.get(f"{API}/settings/current", headers=bearer(laptop_access)).status_code == 200


def test_requests_without_a_token_get_401(api: TestClient) -> None:
    response = api.get(f"{API}/settings/current")
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"
    garbage = api.get(f"{API}/settings/current", headers=bearer("not.a.jwt"))
    assert garbage.status_code == 401
