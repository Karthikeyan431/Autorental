"""Audit entries for sign-in, user, permission and settings changes; the chain verifies;
no secret ever reaches the audit log (rule 11, hard constraint 5)."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from tests.api.conftest import FakeClock, OwnerContext
from tests.api.helpers import (
    API,
    STAFF_PASSWORD,
    bearer,
    login,
    owner_sign_in,
)

EXPECTED_ACTIONS = {
    "user.owner_created",
    "auth.totp_enrolled",
    "auth.login_succeeded",
    "auth.login_failed",
    "user.created",
    "user.updated",
    "user.deactivated",
    "user.reactivated",
    "user.password_reset",
    "user.permissions_changed",
    "auth.password_changed",
    "auth.logout",
    "settings.version_created",
}


def test_audited_actions_are_recorded_and_the_chain_verifies(
    api: TestClient, owner: OwnerContext, clock: FakeClock, app_engine: Engine
) -> None:
    token = owner_sign_in(api, clock, owner.login, owner.password, owner.totp_secret)
    headers = bearer(token)
    secrets_seen: list[str] = [owner.password, owner.totp_secret, token, *owner.recovery_codes]

    login(api, owner.login, "Wrong-password-000")
    created = api.post(
        f"{API}/users", headers=headers, json={"name": "Test Staff 401", "mobile": "9000000401"}
    ).json()
    staff_id = created["user"]["id"]
    secrets_seen.append(created["temporary_password"])

    api.patch(f"{API}/users/{staff_id}", headers=headers, json={"name": "Test Staff 401 B"})
    api.put(
        f"{API}/users/{staff_id}/permissions",
        headers=headers,
        json={"permissions": ["drivers.create"]},
    )
    api.post(f"{API}/users/{staff_id}/deactivate", headers=headers, json={"reason": "Left"})
    api.post(f"{API}/users/{staff_id}/reactivate", headers=headers)
    reset = api.post(f"{API}/users/{staff_id}/reset-password", headers=headers).json()
    secrets_seen.append(reset["temporary_password"])

    staff_login = login(api, "9000000401", reset["temporary_password"]).json()
    staff_token = staff_login["access_token"]
    secrets_seen.append(staff_token)
    api.post(
        f"{API}/auth/change-password",
        headers=bearer(staff_token),
        json={"current_password": reset["temporary_password"], "new_password": STAFF_PASSWORD},
    )
    api.post(f"{API}/settings", headers=headers, json={"staff_limit": 12})
    api.post(f"{API}/auth/logout", headers=bearer(staff_token))

    with Session(app_engine) as session:
        entries = session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        actions = {entry.action for entry in entries}
        dumped = json.dumps(
            [[e.before, e.after, e.reason, e.action, e.entity_type] for e in entries]
        )
    missing = EXPECTED_ACTIONS - actions
    assert not missing, f"missing audit actions: {missing}"
    for secret in [*secrets_seen, STAFF_PASSWORD, "Wrong-password-000"]:
        assert secret not in dumped

    verify = api.get(f"{API}/audit-logs/verify", headers=headers)
    assert verify.status_code == 200
    body = verify.json()
    assert body["ok"] is True
    assert body["checked"] == len(entries)


def test_a_failed_login_records_the_reason_but_not_the_identifier(
    api: TestClient, owner: OwnerContext, app_engine: Engine
) -> None:
    login(api, "9000000777", "Wrong-password-000")
    with Session(app_engine) as session:
        entry = session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "auth.login_failed")
            .order_by(AuditLog.id.desc())
        ).first()
    assert entry is not None
    assert entry.entity_id is None
    assert entry.reason == "unknown_account"
    assert "9000000777" not in json.dumps([entry.before, entry.after, entry.reason])


def test_the_owner_lists_audit_entries(api: TestClient, owner: OwnerContext) -> None:
    response = api.get(f"{API}/audit-logs?page_size=5", headers=bearer(owner.token))
    assert response.status_code == 200
    body = response.json()
    assert body["page_size"] == 5
    assert body["total"] >= 3
    first = body["items"][0]
    assert {"id", "occurred_at", "actor_id", "actor_name", "action", "entity_type"} <= set(first)
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids, reverse=True)  # newest first
