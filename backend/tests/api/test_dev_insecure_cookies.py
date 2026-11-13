"""DEV_INSECURE_COOKIES (development only): sign-in survives reloads over plain http on the LAN.

The cookies keep httpOnly and SameSite=Strict; only the Secure flag is dropped. Every other
environment keeps Secure, and production refuses the setting (tests/core/test_config.py).
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.api.conftest import FakeClock, StaffFactory
from tests.api.helpers import CSRF_COOKIE, REFRESH_COOKIE, STAFF_PASSWORD, login

MOBILE = "9000000301"


@pytest.fixture
def dev_app(test_settings: Settings, clean_db: None, clock: FakeClock) -> Iterator[FastAPI]:
    settings = test_settings.model_copy(
        update={"APP_ENV": "development", "DEV_INSECURE_COOKIES": True}
    )
    application = create_app(settings)
    yield application
    application.state.engine.dispose()


def _cookie_headers(client: TestClient) -> dict[str, str]:
    response = login(client, MOBILE, STAFF_PASSWORD)
    assert response.status_code == 200, response.text
    headers = response.headers.get_list("set-cookie")
    return {
        name: next(h for h in headers if h.startswith(f"{name}=")).lower()
        for name in (REFRESH_COOKIE, CSRF_COOKIE)
    }


def test_development_lan_mode_drops_only_the_secure_flag(
    dev_app: FastAPI, staff_factory: StaffFactory
) -> None:
    staff_factory(name="Test Staff 301", mobile=MOBILE)
    client = TestClient(dev_app, base_url="http://testserver", raise_server_exceptions=False)
    cookies = _cookie_headers(client)
    for name, header in cookies.items():
        assert "secure" not in header, name
        assert "samesite=strict" in header, name
    assert "httponly" in cookies[REFRESH_COOKIE]

    # Over plain http the refresh cookie now comes back, so a reload keeps the session.
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200, refreshed.text


def test_cookies_are_secure_by_default(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(name="Test Staff 301", mobile=MOBILE)
    for name, header in _cookie_headers(api).items():
        assert "secure" in header, name
