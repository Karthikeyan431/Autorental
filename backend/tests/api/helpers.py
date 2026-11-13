"""Helpers for the API tests. All data is obviously fake (hard constraint 7)."""

from typing import Any, Protocol

import pyotp
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.modules.users.service import create_owner, create_staff

API = "/api/v1"
OWNER_MOBILE = "9000000001"
OWNER_PASSWORD = "Kite-river-lamp-0001"
STAFF_PASSWORD = "Plum-stone-bell-0001"
REFRESH_COOKIE = "arms_refresh"
CSRF_COOKIE = "arms_csrf"


class Clock(Protocol):
    def advance(self, **kwargs: float) -> None: ...

    def now(self) -> Any: ...


def make_owner(engine: Engine, *, password: str = OWNER_PASSWORD) -> int:
    with Session(engine) as session, session.begin():
        user = create_owner(
            session,
            name="Test Owner",
            mobile=OWNER_MOBILE,
            email="owner@example.test",
            password=password,
        )
        return user.id


def make_staff(
    engine: Engine,
    *,
    name: str,
    mobile: str,
    email: str | None = None,
    password: str = STAFF_PASSWORD,
    must_change_password: bool = False,
    is_active: bool = True,
) -> int:
    with Session(engine) as session, session.begin():
        user, _ = create_staff(
            session,
            actor_id=None,
            name=name,
            mobile=mobile,
            email=email,
            password=password,
            must_change_password=must_change_password,
        )
        if not is_active:
            user.is_active = False
        return user.id


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, login_id: str, password: str) -> Response:
    response: Response = client.post(
        f"{API}/auth/login", json={"login": login_id, "password": password}
    )
    return response


def staff_token(client: TestClient, mobile: str, password: str = STAFF_PASSWORD) -> str:
    response = login(client, mobile, password)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    return str(body["access_token"])


def totp_code(secret: str, clock: Clock) -> str:
    return pyotp.TOTP(secret).at(clock.now())


def enrol_owner(
    client: TestClient, clock: Clock, login_id: str, password: str
) -> tuple[str, list[str], str]:
    """First sign-in: password, TOTP setup, confirm. Returns (secret, recovery codes, token)."""
    response = login(client, login_id, password)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "totp_setup_required"
    challenge = body["challenge_token"]

    setup = client.post(f"{API}/auth/totp/setup", json={"challenge_token": challenge})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]

    confirm = client.post(
        f"{API}/auth/totp/confirm",
        json={"challenge_token": challenge, "code": totp_code(secret, clock)},
    )
    assert confirm.status_code == 200, confirm.text
    data = confirm.json()
    return secret, list(data["recovery_codes"]), str(data["access_token"])


def owner_challenge(client: TestClient, login_id: str, password: str) -> str:
    response = login(client, login_id, password)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "totp_required"
    assert "access_token" not in body
    return str(body["challenge_token"])


def owner_sign_in(
    client: TestClient, clock: Clock, login_id: str, password: str, secret: str
) -> str:
    """A later owner sign-in. Moves to the next 30-second window so the code is fresh."""
    clock.advance(seconds=30)
    challenge = owner_challenge(client, login_id, password)
    response = client.post(
        f"{API}/auth/totp", json={"challenge_token": challenge, "code": totp_code(secret, clock)}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def refresh(client: TestClient, refresh_value: str, csrf: str | None) -> Response:
    """Call /auth/refresh with exactly the given cookies (the jar is cleared first)."""
    client.cookies.clear()
    cookie = f"{REFRESH_COOKIE}={refresh_value}; {CSRF_COOKIE}={csrf or 'none'}"
    headers = {"Cookie": cookie}
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    response: Response = client.post(f"{API}/auth/refresh", headers=headers)
    return response


def error_code(response: Response) -> str:
    return str(response.json()["error"]["code"])
