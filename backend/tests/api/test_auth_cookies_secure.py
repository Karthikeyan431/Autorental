"""The sign-in cookies are always Secure, httpOnly (refresh) and SameSite=Strict, in every
environment, development included. Phone testing uses https (scripts\\dev.ps1 -Lan), so there
is no switch to drop the Secure flag (DEV_INSECURE_COOKIES was removed)."""

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
    application = create_app(test_settings.model_copy(update={"APP_ENV": "development"}))
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


def _assert_secure(cookies: dict[str, str]) -> None:
    for name, header in cookies.items():
        assert "secure" in header, name
        assert "samesite=strict" in header, name
    assert "httponly" in cookies[REFRESH_COOKIE]
    assert "httponly" not in cookies[CSRF_COOKIE]  # the page echoes it in X-CSRF-Token


def test_cookies_are_secure(api: TestClient, staff_factory: StaffFactory) -> None:
    staff_factory(name="Test Staff 301", mobile=MOBILE)
    _assert_secure(_cookie_headers(api))


def test_cookies_are_secure_in_development_too(
    dev_app: FastAPI, staff_factory: StaffFactory
) -> None:
    staff_factory(name="Test Staff 301", mobile=MOBILE)
    client = TestClient(dev_app, base_url="https://testserver", raise_server_exceptions=False)
    _assert_secure(_cookie_headers(client))
