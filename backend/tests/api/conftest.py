"""Fixtures for API tests that go through HTTP and commit to arms_test.

These tests commit real rows (sign-in must record failures even when the request is refused),
so `clean_db` (tests/conftest.py) empties the tables before and after each test.

The clock is controllable: `clock.advance(minutes=15)` moves the time the auth code sees
(lockouts, token expiry, TOTP windows) without sleeping.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

import app.core.time as clock_module
from app.core.config import Settings
from app.main import create_app
from app.modules.settings.schemas import SettingsChanges
from app.modules.settings.service import create_settings_version
from tests.api.helpers import (
    OWNER_MOBILE,
    OWNER_PASSWORD,
    enrol_owner,
    make_owner,
    make_staff,
    staff_token,
)


class FakeClock:
    """Real time plus an offset that tests can move forward."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset

    def advance(self, **kwargs: float) -> None:
        self.offset += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock_module, "utc_now", fake.now)
    return fake


@pytest.fixture
def app(test_settings: Settings, clean_db: None, clock: FakeClock) -> Iterator[FastAPI]:
    application = create_app(test_settings)
    yield application
    application.state.engine.dispose()


ClientFactory = Callable[[str], TestClient]


@pytest.fixture
def make_client(app: FastAPI) -> ClientFactory:
    """A client from a given IP address, over https so Secure cookies are sent back."""

    def factory(ip: str = "127.0.0.1") -> TestClient:
        return TestClient(
            app, base_url="https://testserver", raise_server_exceptions=False, client=(ip, 50000)
        )

    return factory


@pytest.fixture
def api(make_client: ClientFactory) -> TestClient:
    return make_client("127.0.0.1")


@pytest.fixture
def app_db(app_engine: Engine) -> Callable[[], Session]:
    """A committing app_user session factory for test setup."""

    def factory() -> Session:
        return Session(app_engine, expire_on_commit=False)

    return factory


@pytest.fixture
def settings_v1(app_engine: Engine, clean_db: None) -> None:
    with Session(app_engine) as session, session.begin():
        create_settings_version(
            session,
            SettingsChanges(rent_due_time=time(10, 0), business_name="Test Auto Rentals"),
            actor_id=None,
        )


@dataclass
class OwnerContext:
    id: int
    login: str
    password: str
    totp_secret: str
    recovery_codes: list[str]
    token: str


@pytest.fixture
def owner(api: TestClient, app_engine: Engine, clock: FakeClock, settings_v1: None) -> OwnerContext:
    """An owner who has enrolled TOTP and is signed in."""
    owner_id = make_owner(app_engine)
    secret, codes, token = enrol_owner(api, clock, OWNER_MOBILE, OWNER_PASSWORD)
    return OwnerContext(owner_id, OWNER_MOBILE, OWNER_PASSWORD, secret, codes, token)


StaffFactory = Callable[..., int]


@pytest.fixture
def staff_factory(app_engine: Engine, clean_db: None) -> StaffFactory:
    counter = {"n": 100}

    def factory(**kwargs: object) -> int:
        counter["n"] += 1
        kwargs.setdefault("mobile", f"9000000{counter['n']:03d}")
        kwargs.setdefault("name", f"Test Staff {counter['n']:03d}")
        return make_staff(app_engine, **kwargs)  # type: ignore[arg-type]

    return factory


@dataclass
class Team:
    """The owner and two staff members, all signed in."""

    owner: OwnerContext
    staff_a_id: int
    staff_a: str  # access token
    staff_b_id: int
    staff_b: str


STAFF_A_MOBILE = "9000000201"
STAFF_B_MOBILE = "9000000202"


@pytest.fixture
def team(api: TestClient, owner: OwnerContext, staff_factory: StaffFactory) -> Team:
    staff_a_id = staff_factory(name="Test Staff 201", mobile=STAFF_A_MOBILE)
    staff_b_id = staff_factory(name="Test Staff 202", mobile=STAFF_B_MOBILE)
    return Team(
        owner=owner,
        staff_a_id=staff_a_id,
        staff_a=staff_token(api, STAFF_A_MOBILE),
        staff_b_id=staff_b_id,
        staff_b=staff_token(api, STAFF_B_MOBILE),
    )
