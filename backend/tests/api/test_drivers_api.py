"""Drivers: creator and manager (rule 14), editing rights (N1), duplicates, history, timeline."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    create_driver,
    driver_payload,
    error_code,
    jpeg_bytes,
    record_consent,
    submitted_identity,
)
from tests.api.helpers import API, bearer


def test_new_driver_gets_a_code_and_the_creator_as_creator_and_manager(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    assert re.fullmatch(r"D\d{4,}", driver["code"])
    assert driver["created_by"]["id"] == team.staff_a_id
    assert driver["managed_by"]["id"] == team.staff_a_id
    assert driver["created_by"]["name"] == "Test Staff 201"
    assert driver["account_status"] == "active"
    assert driver["payment_rhythm"] == "daily"
    assert driver["mobile"] == "+919000000001"

    second = create_driver(api, team.staff_a, 2)
    assert int(second["code"][1:]) == int(driver["code"][1:]) + 1


def test_created_by_and_managed_by_cannot_be_changed_by_edit(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    for field, value in (("created_by", team.staff_b_id), ("managed_by", team.staff_b_id)):
        response = api.patch(
            f"{API}/drivers/{driver['id']}",
            json={field: value},
            headers=bearer(team.owner.token),
        )
        assert response.status_code == 422, field
    again = api.get(f"{API}/drivers/{driver['id']}", headers=bearer(team.owner.token)).json()
    assert again["created_by"]["id"] == team.staff_a_id
    assert again["managed_by"]["id"] == team.staff_a_id


def test_staff_cannot_reassign_a_manager(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    response = api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test reassignment"},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 403


def test_owner_reassignment_writes_history_and_an_audit_entry(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a)
    owner = bearer(team.owner.token)

    missing_reason = api.post(
        f"{API}/drivers/{driver['id']}/manager", json={"staff_id": team.staff_b_id}, headers=owner
    )
    assert missing_reason.status_code == 422

    response = api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test reassignment"},
        headers=owner,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["managed_by"]["id"] == team.staff_b_id
    assert body["created_by"]["id"] == team.staff_a_id  # never changes

    history = api.get(f"{API}/drivers/{driver['id']}/manager-history", headers=owner).json()
    assert [(h["staff"]["id"], h["to_at"] is None) for h in history] == [
        (team.staff_b_id, True),
        (team.staff_a_id, False),
    ]
    assert history[0]["reason"] == "Test reassignment"
    assert history[0]["changed_by"]["id"] == team.owner.id

    with Session(app_engine) as session:
        entry = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "driver.manager_changed", AuditLog.entity_id == driver["id"]
            )
        ).one()
    assert entry.actor_id == team.owner.id
    assert entry.before == {"managed_by": team.staff_a_id}
    assert entry.after == {"managed_by": team.staff_b_id}
    assert entry.reason == "Test reassignment"


def test_reassigning_to_an_inactive_or_unknown_user_is_refused(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    owner = bearer(team.owner.token)
    api.post(f"{API}/users/{team.staff_b_id}/deactivate", json={"reason": "Test"}, headers=owner)
    for staff_id in (team.staff_b_id, 999_999):
        response = api.post(
            f"{API}/drivers/{driver['id']}/manager",
            json={"staff_id": staff_id, "reason": "Test"},
            headers=owner,
        )
        assert response.status_code == 409
        assert error_code(response) == "MANAGER_NOT_AVAILABLE"


def test_staff_can_edit_only_the_drivers_they_manage(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    url = f"{API}/drivers/{driver['id']}"

    own = api.patch(url, json={"address": "Test address changed"}, headers=bearer(team.staff_a))
    assert own.status_code == 200, own.text
    assert "address" not in own.json()  # masked in every response (D45)

    other = api.patch(url, json={"address": "Not mine"}, headers=bearer(team.staff_b))
    assert other.status_code == 403
    assert error_code(other) == "DRIVER_NOT_EDITABLE"

    # Staff B can still see the driver (N1: see all drivers).
    assert api.get(url, headers=bearer(team.staff_b)).status_code == 200

    owner = api.patch(url, json={"address": "Owner edit"}, headers=bearer(team.owner.token))
    assert owner.status_code == 200


def test_drivers_edit_any_lets_staff_edit_every_driver_except_masked_fields(
    api: TestClient, team: Team
) -> None:
    """D46 (N17) replaces the Week 3 rule: drivers.edit_any covers the unmasked fields only."""
    driver = create_driver(api, team.staff_a)
    grant = api.put(
        f"{API}/users/{team.staff_b_id}/permissions",
        json={"permissions": ["drivers.create", "drivers.edit_own", "drivers.edit_any"]},
        headers=bearer(team.owner.token),
    )
    assert grant.status_code == 200, grant.text
    response = api.patch(
        f"{API}/drivers/{driver['id']}",
        json={"emergency_name": "Test Contact 999"},
        headers=bearer(team.staff_b),
    )
    assert response.status_code == 200, response.text
    masked = api.patch(
        f"{API}/drivers/{driver['id']}",
        json={"address": "Edited with edit_any"},
        headers=bearer(team.staff_b),
    )
    assert masked.status_code == 403
    assert error_code(masked) == "FIELD_NOT_EDITABLE"


def test_a_duplicate_mobile_is_refused_in_any_format(api: TestClient, team: Team) -> None:
    create_driver(api, team.staff_a, 1)
    for variant in ("+91 90000 00001", "09000000001", "919000000001"):
        response = api.post(
            f"{API}/drivers",
            json=driver_payload(2, mobile=variant),
            headers=bearer(team.staff_b),
        )
        assert response.status_code == 409, variant
        assert error_code(response) == "MOBILE_TAKEN"


def test_an_invalid_mobile_is_refused(api: TestClient, team: Team) -> None:
    response = api.post(
        f"{API}/drivers", json=driver_payload(1, mobile="12345"), headers=bearer(team.staff_a)
    )
    assert response.status_code == 422


def test_creating_a_driver_needs_the_permission(api: TestClient, team: Team) -> None:
    api.put(
        f"{API}/users/{team.staff_b_id}/permissions",
        json={"permissions": ["drivers.edit_own"]},
        headers=bearer(team.owner.token),
    )
    response = api.post(f"{API}/drivers", json=driver_payload(), headers=bearer(team.staff_b))
    assert response.status_code == 403


def test_list_filters_managed_by_me_and_search(api: TestClient, team: Team) -> None:
    mine = create_driver(api, team.staff_a, 1)
    theirs = create_driver(api, team.staff_b, 2)

    everyone = api.get(f"{API}/drivers", headers=bearer(team.staff_a)).json()
    assert {d["id"] for d in everyone["items"]} == {mine["id"], theirs["id"]}

    own = api.get(f"{API}/drivers?mine=true", headers=bearer(team.staff_a)).json()
    assert [d["id"] for d in own["items"]] == [mine["id"]]

    by_b = api.get(
        f"{API}/drivers?managed_by={team.staff_b_id}", headers=bearer(team.owner.token)
    ).json()
    assert [d["id"] for d in by_b["items"]] == [theirs["id"]]

    found = api.get(f"{API}/drivers?search=Driver 002", headers=bearer(team.staff_a)).json()
    assert [d["id"] for d in found["items"]] == [theirs["id"]]
    by_code = api.get(f"{API}/drivers?search={mine['code']}", headers=bearer(team.staff_a)).json()
    assert [d["id"] for d in by_code["items"]] == [mine["id"]]


def test_timeline_lists_the_manager_change(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test reassignment"},
        headers=bearer(team.owner.token),
    )
    timeline = api.get(
        f"{API}/drivers/{driver['id']}/timeline", headers=bearer(team.owner.token)
    ).json()
    actions = [item["action"] for item in timeline]
    assert actions[0] == "driver.manager_changed"
    assert "driver.created" in actions
    change = timeline[0]
    assert change["actor"]["id"] == team.owner.id
    assert change["reason"] == "Test reassignment"


def test_timeline_hides_kyc_entries_from_staff_without_kyc_access(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    submitted_identity(api, team.staff_a, driver["id"])

    def actions(token: str) -> set[str]:
        response = api.get(f"{API}/drivers/{driver['id']}/timeline", headers=bearer(token))
        assert response.status_code == 200
        return {item["action"] for item in response.json()}

    manager_view = actions(team.staff_a)
    assert {"consent.recorded", "kyc.attempt_created", "kyc.submitted"} <= manager_view
    other_view = actions(team.staff_b)
    assert "driver.created" in other_view
    assert not {a for a in other_view if a.startswith(("kyc.", "consent.", "document."))}


def test_photo_is_visible_to_every_staff_member(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    response = api.post(
        f"{API}/drivers/{driver['id']}/photo",
        files={"file": ("photo.jpg", jpeg_bytes(), "image/jpeg")},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 200, response.text
    photo_id = response.json()["photo_document_id"]
    assert photo_id is not None
    content = api.get(f"{API}/documents/{photo_id}/content", headers=bearer(team.staff_b))
    assert content.status_code == 200


def test_photo_upload_follows_edit_rights(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    response = api.post(
        f"{API}/drivers/{driver['id']}/photo",
        files={"file": ("photo.jpg", jpeg_bytes(), "image/jpeg")},
        headers=bearer(team.staff_b),
    )
    assert response.status_code == 403


def test_suspend_and_reactivate_need_drivers_restrict(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    url = f"{API}/drivers/{driver['id']}"
    refused = api.post(f"{url}/suspend", json={"reason": "Test"}, headers=bearer(team.staff_a))
    assert refused.status_code == 403

    owner = bearer(team.owner.token)
    suspended = api.post(f"{url}/suspend", json={"reason": "Test suspension"}, headers=owner)
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["account_status"] == "suspended"
    again = api.post(f"{url}/suspend", json={"reason": "Test"}, headers=owner)
    assert again.status_code == 409

    reactivated = api.post(f"{url}/reactivate", json={"reason": "Test"}, headers=owner)
    assert reactivated.status_code == 200
    assert reactivated.json()["account_status"] == "active"


def test_restrictions_are_placed_and_lifted_by_the_owner(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    owner = bearer(team.owner.token)
    url = f"{API}/drivers/{driver['id']}/restrictions"

    staff_try = api.post(
        url, json={"reason": "Test", "is_blocking": True}, headers=bearer(team.staff_a)
    )
    assert staff_try.status_code == 403

    placed = api.post(url, json={"reason": "Test block", "is_blocking": True}, headers=owner)
    assert placed.status_code == 201, placed.text
    restriction_id = placed.json()["id"]
    listed = api.get(url, headers=bearer(team.staff_b)).json()
    assert [r["id"] for r in listed] == [restriction_id]

    lifted = api.post(f"{API}/restrictions/{restriction_id}/lift", json={}, headers=owner)
    assert lifted.status_code == 200
    assert lifted.json()["lifted_at"] is not None
    twice = api.post(f"{API}/restrictions/{restriction_id}/lift", json={}, headers=owner)
    assert twice.status_code == 409


def test_driver_fields_refuse_aadhaar_like_numbers(api: TestClient, team: Team) -> None:
    for field in ("address", "full_name", "emergency_name"):
        response = api.post(
            f"{API}/drivers",
            json=driver_payload(1, **{field: "Test 1234 5678 9012"}),
            headers=bearer(team.staff_a),
        )
        assert response.status_code == 422, field


def test_reading_drivers_needs_sign_in(api: TestClient, team: Team) -> None:
    assert api.get(f"{API}/drivers").status_code == 401
