"""Staff management is owner-only; owner-only permission codes can never be granted."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.permissions import OWNER_ONLY, STAFF_DEFAULTS, Permission
from tests.api.conftest import OwnerContext, StaffFactory
from tests.api.helpers import API, bearer, error_code, login, staff_token

OWNER_ONLY_ROUTES = [
    ("GET", "/users"),
    ("POST", "/users"),
    ("GET", "/users/1"),
    ("PATCH", "/users/1"),
    ("POST", "/users/1/deactivate"),
    ("POST", "/users/1/reactivate"),
    ("POST", "/users/1/reset-password"),
    ("PUT", "/users/1/permissions"),
    ("GET", "/permissions"),
    ("POST", "/settings"),
    ("GET", "/audit-logs"),
    ("GET", "/audit-logs/verify"),
]


@pytest.mark.parametrize(("method", "path"), OWNER_ONLY_ROUTES)
def test_staff_calling_an_owner_only_endpoint_gets_403(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory, method: str, path: str
) -> None:
    staff_factory(mobile="9000000101")
    token = staff_token(api, "9000000101")
    response = api.request(method, f"{API}{path}", headers=bearer(token), json={})
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_owner_creates_staff_with_default_permissions(api: TestClient, owner: OwnerContext) -> None:
    response = api.post(
        f"{API}/users",
        headers=bearer(owner.token),
        json={"name": "Test Staff 201", "mobile": "9000000201", "email": "staff201@example.test"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    user = body["user"]
    assert user["role"] == "staff"
    assert user["mobile"] == "+919000000201"
    assert user["must_change_password"] is True
    assert set(user["permissions"]) == {p.value for p in STAFF_DEFAULTS}
    assert "drivers.restrict" not in user["permissions"]  # off by default (D9)
    assert "adjustments.request" in user["permissions"]  # on by default (D9)

    signed_in = login(api, "9000000201", body["temporary_password"])
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["must_change_password"] is True


def test_owner_sets_grantable_permissions(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory, app_engine: Engine
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    wanted = ["drivers.create", "drivers.restrict", "reports.all"]
    response = api.put(
        f"{API}/users/{staff_id}/permissions",
        headers=bearer(owner.token),
        json={"permissions": wanted},
    )
    assert response.status_code == 200, response.text
    assert sorted(response.json()["permissions"]) == sorted(wanted)

    signed_in = login(api, "9000000101", "Plum-stone-bell-0001").json()
    assert sorted(signed_in["user"]["permissions"]) == sorted(wanted)

    with Session(app_engine) as session:
        entry = session.scalars(
            select(AuditLog).where(AuditLog.action == "user.permissions_changed")
        ).one()
    assert entry.entity_id == staff_id
    assert entry.after is not None
    assert sorted(entry.after["permissions"]) == sorted(wanted)
    assert entry.before is not None
    assert "drivers.restrict" not in entry.before["permissions"]


@pytest.mark.parametrize("code", sorted(p.value for p in OWNER_ONLY))
def test_granting_an_owner_only_code_is_refused(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory, code: str
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    response = api.put(
        f"{API}/users/{staff_id}/permissions",
        headers=bearer(owner.token),
        json={"permissions": ["drivers.create", code]},
    )
    assert response.status_code == 409
    assert error_code(response) == "PERMISSION_NOT_GRANTABLE"

    unchanged = api.get(f"{API}/users/{staff_id}", headers=bearer(owner.token)).json()
    assert code not in unchanged["permissions"]
    assert set(unchanged["permissions"]) == {p.value for p in STAFF_DEFAULTS}


def test_an_unknown_permission_code_is_a_validation_error(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    response = api.put(
        f"{API}/users/{staff_id}/permissions",
        headers=bearer(owner.token),
        json={"permissions": ["drivers.fly"]},
    )
    assert response.status_code == 422


def test_the_database_refuses_an_owner_only_grant(db: Session) -> None:
    staff_id = db.execute(
        text(
            "INSERT INTO users (name, mobile, password_hash, role) "
            "VALUES ('Test Staff 301', '+919000000301', 'x', 'staff') RETURNING id"
        )
    ).scalar_one()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO user_permissions (user_id, permission_code) "
                "VALUES (:user_id, 'payments.approve')"
            ),
            {"user_id": staff_id},
        )


def test_owner_permissions_cannot_be_edited(api: TestClient, owner: OwnerContext) -> None:
    response = api.put(
        f"{API}/users/{owner.id}/permissions",
        headers=bearer(owner.token),
        json={"permissions": []},
    )
    assert response.status_code == 409
    assert error_code(response) == "OWNER_PERMISSIONS_FIXED"


def test_the_owner_cannot_be_deactivated(api: TestClient, owner: OwnerContext) -> None:
    response = api.post(f"{API}/users/{owner.id}/deactivate", headers=bearer(owner.token), json={})
    assert response.status_code == 409
    assert error_code(response) == "OWNER_CANNOT_BE_DEACTIVATED"


def test_duplicate_mobile_and_email_are_refused(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_factory(mobile="9000000101", email="staff101@example.test")
    dup_mobile = api.post(
        f"{API}/users",
        headers=bearer(owner.token),
        json={"name": "Test Staff 202", "mobile": "+91 90000 00101"},
    )
    assert dup_mobile.status_code == 409
    assert error_code(dup_mobile) == "MOBILE_TAKEN"
    dup_email = api.post(
        f"{API}/users",
        headers=bearer(owner.token),
        json={"name": "Test Staff 203", "mobile": "9000000203", "email": "STAFF101@example.test"},
    )
    assert dup_email.status_code == 409
    assert error_code(dup_email) == "EMAIL_TAKEN"


def test_invalid_mobile_is_refused(api: TestClient, owner: OwnerContext) -> None:
    response = api.post(
        f"{API}/users",
        headers=bearer(owner.token),
        json={"name": "Test Staff 204", "mobile": "12345"},
    )
    assert response.status_code == 422


def test_owner_edits_staff_details(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    staff_id = staff_factory(mobile="9000000101")
    response = api.patch(
        f"{API}/users/{staff_id}",
        headers=bearer(owner.token),
        json={"name": "Test Staff 101 Renamed", "email": "renamed101@example.test"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Test Staff 101 Renamed"
    assert response.json()["email"] == "renamed101@example.test"


def test_users_list_is_paginated_and_searchable(
    api: TestClient, owner: OwnerContext, staff_factory: StaffFactory
) -> None:
    for _ in range(3):
        staff_factory()
    staff_factory(name="Test Staff Findme", mobile="9000000150")
    page = api.get(f"{API}/users?page=1&page_size=2", headers=bearer(owner.token)).json()
    assert page["total"] == 5  # owner + 4 staff
    assert len(page["items"]) == 2
    found = api.get(f"{API}/users?search=findme", headers=bearer(owner.token)).json()
    assert [u["name"] for u in found["items"]] == ["Test Staff Findme"]
    staff_only = api.get(f"{API}/users?role=staff", headers=bearer(owner.token)).json()
    assert staff_only["total"] == 4


def test_unknown_user_is_404(api: TestClient, owner: OwnerContext) -> None:
    assert api.get(f"{API}/users/999999", headers=bearer(owner.token)).status_code == 404


def test_permission_catalogue_marks_owner_only_codes(api: TestClient, owner: OwnerContext) -> None:
    catalogue = api.get(f"{API}/permissions", headers=bearer(owner.token)).json()
    by_code = {item["code"]: item for item in catalogue["items"]}
    assert set(by_code) == {p.value for p in Permission}
    assert by_code["adjustments.decide"]["grantable"] is False
    assert by_code["drivers.restrict"]["grantable"] is True
    assert by_code["drivers.restrict"]["staff_default"] is False
    assert by_code["adjustments.request"]["staff_default"] is True
