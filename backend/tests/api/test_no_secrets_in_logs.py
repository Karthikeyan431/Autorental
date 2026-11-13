"""No password, token, TOTP secret or code appears in the logs (Week 2 "Done when")."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from tests.api.conftest import FakeClock, OwnerContext, StaffFactory
from tests.api.helpers import (
    API,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    STAFF_PASSWORD,
    bearer,
    login,
    owner_challenge,
    refresh,
    totp_code,
)


def test_a_full_sign_in_flow_logs_no_secrets(
    api: TestClient,
    owner: OwnerContext,
    staff_factory: StaffFactory,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    secrets_seen = [owner.password, owner.totp_secret, STAFF_PASSWORD, *owner.recovery_codes]

    clock.advance(seconds=30)
    challenge = owner_challenge(api, owner.login, owner.password)
    code = totp_code(owner.totp_secret, clock)
    signed_in = api.post(f"{API}/auth/totp", json={"challenge_token": challenge, "code": code})
    owner_token = signed_in.json()["access_token"]
    secrets_seen += [challenge, code, owner_token]

    staff_factory(mobile="9000000101")
    login(api, "9000000101", "Wrong-password-000")
    staff = login(api, "9000000101", STAFF_PASSWORD)
    refresh_value = staff.cookies.get(REFRESH_COOKIE)
    csrf = staff.cookies.get(CSRF_COOKIE)
    assert refresh_value and csrf
    rotated = refresh(api, refresh_value, csrf)
    secrets_seen += [staff.json()["access_token"], refresh_value, csrf]
    secrets_seen += [rotated.json()["access_token"], rotated.cookies.get(REFRESH_COOKIE) or ""]

    created = api.post(
        f"{API}/users",
        headers=bearer(owner_token),
        json={"name": "Test Staff 501", "mobile": "9000000501"},
    ).json()
    secrets_seen.append(created["temporary_password"])

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(record) for record in caplog.records)
    output += "\n".join(str(record.__dict__) for record in caplog.records)
    assert caplog.records, "expected some log records"
    for secret in filter(None, secrets_seen):
        assert secret not in output
