"""Autos (Week 4; docs/data-model.md "vehicles"; rule 2 groundwork; Q29).

* Registration numbers are unique after normalising spaces, hyphens and case.
* Staff cannot set `rented`: only the agreements service (Week 5) sets it and back.
* An auto in `maintenance` or `inactive` cannot be selected for an agreement.
* Papers (insurance, fitness, permit, pollution) with expiry alerts for the Q29 kinds, raised as
  soon as a paper is saved as well as by the daily job.
* Writes need `vehicles.manage`; every signed-in user can read.
"""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.time import business_date
from tests.api.conftest import Team
from tests.api.driver_helpers import error_code, jpeg_bytes
from tests.api.helpers import API, bearer


def _create(
    api: TestClient, token: str, registration: str = "XX 00 TT 0101", **extra: Any
) -> Response:
    body: dict[str, Any] = {
        "registration_number": registration,
        "make": "Demo Motors",
        "model": "Test 3W",
        "year": 2022,
        "fuel_type": "cng",
    }
    body.update(extra)
    response: Response = api.post(f"{API}/vehicles", json=body, headers=bearer(token))
    return response


def _vehicle(api: TestClient, token: str, registration: str = "XX 00 TT 0101") -> dict[str, Any]:
    response = _create(api, token, registration)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _status(api: TestClient, token: str, vehicle_id: int, status: str) -> Response:
    response: Response = api.post(
        f"{API}/vehicles/{vehicle_id}/status",
        json={"status": status, "reason": "Test reason"},
        headers=bearer(token),
    )
    return response


def _paper(
    api: TestClient,
    token: str,
    vehicle_id: int,
    kind: str,
    valid_until: str,
    *,
    with_file: bool = False,
    **extra: str,
) -> Response:
    data = {"kind": kind, "valid_until": valid_until, "number": "DEMO-POLICY-1", **extra}
    files = {"file": ("paper.jpg", jpeg_bytes(), "image/jpeg")} if with_file else None
    response: Response = api.post(
        f"{API}/vehicles/{vehicle_id}/compliance", data=data, files=files, headers=bearer(token)
    )
    return response


# --- Registration ---------------------------------------------------------------------------------


def test_staff_register_an_auto_with_a_normalised_number(api: TestClient, team: Team) -> None:
    created = _vehicle(api, team.staff_a, "xx 00-tt 0101")
    assert created["registration_number"] == "XX00TT0101"
    assert created["status"] == "available"
    assert created["selectable"] is True
    listed = api.get(f"{API}/vehicles", headers=bearer(team.staff_b)).json()
    assert [v["registration_number"] for v in listed["items"]] == ["XX00TT0101"]


def test_a_duplicate_registration_number_is_refused(api: TestClient, team: Team) -> None:
    _vehicle(api, team.staff_a, "XX00TT0101")
    for variant in ("xx 00 tt 0101", "XX-00-TT-0101", " xx00tt0101 "):
        response = _create(api, team.staff_b, variant)
        assert response.status_code == 409, variant
        assert error_code(response) == "VEHICLE_REGISTRATION_TAKEN"


def test_a_duplicate_is_refused_by_the_database_too(
    app_engine: Engine, api: TestClient, team: Team
) -> None:
    _vehicle(api, team.staff_a, "XX00TT0101")
    with pytest.raises(Exception, match="registration_number"), app_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vehicles (registration_number, make, model, status) "
                "VALUES ('XX00TT0101', 'Demo', 'Demo', 'available')"
            )
        )


def test_an_invalid_registration_number_is_refused(api: TestClient, team: Team) -> None:
    for bad in ("", "AB", "XX00TT0101!", "X" * 20):
        assert _create(api, team.staff_a, bad).status_code == 422, bad


def test_writes_need_vehicles_manage(api: TestClient, team: Team) -> None:
    revoke = api.put(
        f"{API}/users/{team.staff_b_id}/permissions",
        json={"permissions": ["drivers.create", "drivers.edit_own"]},
        headers=bearer(team.owner.token),
    )
    assert revoke.status_code == 200, revoke.text
    assert _create(api, team.staff_b).status_code == 403
    vehicle = _vehicle(api, team.staff_a)
    # Reading stays open to every signed-in user.
    assert (
        api.get(f"{API}/vehicles/{vehicle['id']}", headers=bearer(team.staff_b)).status_code == 200
    )
    assert _status(api, team.staff_b, vehicle["id"], "maintenance").status_code == 403
    edit = api.patch(
        f"{API}/vehicles/{vehicle['id']}", json={"notes": "x"}, headers=bearer(team.staff_b)
    )
    assert edit.status_code == 403
    assert _create(api, team.owner.token, "XX00TT0102").status_code == 201


def test_editing_an_auto_is_audited(api: TestClient, team: Team, app_engine: Engine) -> None:
    vehicle = _vehicle(api, team.staff_a)
    response = api.patch(
        f"{API}/vehicles/{vehicle['id']}",
        json={"model": "Test 3W Plus", "notes": "Demo note"},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "Test 3W Plus"
    with app_engine.connect() as connection:
        actions = (
            connection.execute(
                text(
                    "SELECT action FROM audit_logs "
                    "WHERE entity_type = 'vehicle' AND entity_id = :id "
                    "ORDER BY id"
                ),
                {"id": vehicle["id"]},
            )
            .scalars()
            .all()
        )
    assert actions == ["vehicle.created", "vehicle.updated"]


# --- Status ---------------------------------------------------------------------------------------


def test_staff_cannot_set_rented(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    response = _status(api, team.owner.token, vehicle["id"], "rented")
    assert response.status_code == 409
    assert error_code(response) == "VEHICLE_STATUS_NOT_ALLOWED"


def test_maintenance_and_back(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    to_maintenance = _status(api, team.staff_a, vehicle["id"], "maintenance")
    assert to_maintenance.status_code == 200, to_maintenance.text
    assert to_maintenance.json()["status"] == "maintenance"
    assert to_maintenance.json()["selectable"] is False
    back = _status(api, team.staff_a, vehicle["id"], "available")
    assert back.json()["status"] == "available"
    assert back.json()["selectable"] is True
    same = _status(api, team.staff_a, vehicle["id"], "available")
    assert same.status_code == 409
    assert error_code(same) == "VEHICLE_STATUS_UNCHANGED"


def test_a_rented_auto_changes_only_through_agreements(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    vehicle = _vehicle(api, team.staff_a)
    with app_engine.begin() as connection:  # what the agreements service will do in Week 5
        connection.execute(
            text("UPDATE vehicles SET status = 'rented' WHERE id = :id"), {"id": vehicle["id"]}
        )
    for target in ("available", "maintenance", "inactive"):
        response = _status(api, team.owner.token, vehicle["id"], target)
        assert response.status_code == 409, target
        assert error_code(response) == "VEHICLE_RENTED"


@pytest.mark.parametrize("status", ["maintenance", "inactive"])
def test_an_auto_in_maintenance_or_inactive_cannot_be_selected(
    api: TestClient, team: Team, app_db: Any, status: str
) -> None:
    from app.modules.vehicles.service import require_selectable_vehicle

    vehicle = _vehicle(api, team.staff_a)
    assert _status(api, team.staff_a, vehicle["id"], status).status_code == 200
    session: Session
    # The check locks the row (FOR UPDATE): close the session so the lock is released.
    with app_db() as session, pytest.raises(AppError) as refused:
        require_selectable_vehicle(session, vehicle["id"])
    assert refused.value.code == "VEHICLE_NOT_AVAILABLE"
    available = api.get(f"{API}/vehicles?status=available", headers=bearer(team.staff_a)).json()
    assert vehicle["id"] not in [v["id"] for v in available["items"]]


# --- Papers ---------------------------------------------------------------------------------------


def test_a_paper_expiring_soon_raises_an_alert_at_once(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    vehicle = _vehicle(api, team.staff_a)
    until = business_date() + timedelta(days=10)
    saved = _paper(api, team.staff_a, vehicle["id"], "insurance", until.isoformat(), with_file=True)
    assert saved.status_code == 201, saved.text
    assert saved.json()["document_id"] is not None
    detail = api.get(f"{API}/vehicles/{vehicle['id']}", headers=bearer(team.staff_a)).json()
    assert [(p["kind"], p["state"]) for p in detail["papers"]] == [("insurance", "expiring")]
    with app_engine.connect() as connection:
        alerts = connection.execute(
            text("SELECT kind, entity_type, entity_id, message FROM alerts")
        ).all()
    assert [(a.kind, a.entity_type, a.entity_id) for a in alerts] == [
        ("vehicle_paper_expiring", "vehicle", vehicle["id"])
    ]
    assert "XX00TT0101" in alerts[0].message
    summary = api.get(f"{API}/vehicles/summary", headers=bearer(team.owner.token)).json()
    assert summary["papers_expiring"] == 1
    assert summary["available"] == 1


def test_a_far_off_paper_and_pollution_raise_no_alert(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    """Q29: insurance, fitness and permit alert; pollution is recorded but does not."""
    vehicle = _vehicle(api, team.staff_a)
    soon = (business_date() + timedelta(days=5)).isoformat()
    later = (business_date() + timedelta(days=300)).isoformat()
    assert _paper(api, team.staff_a, vehicle["id"], "fitness", later).status_code == 201
    assert _paper(api, team.staff_a, vehicle["id"], "pollution", soon).status_code == 201
    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM alerts")).scalar() == 0


def test_paper_dates_and_kind_are_checked(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    today = business_date()
    backwards = _paper(
        api,
        team.staff_a,
        vehicle["id"],
        "permit",
        today.isoformat(),
        valid_from=(today + timedelta(days=1)).isoformat(),
    )
    assert backwards.status_code == 422
    unknown = _paper(api, team.staff_a, vehicle["id"], "road_tax", today.isoformat())
    assert unknown.status_code == 422


def test_vehicle_papers_are_visible_to_all_staff(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    until = (business_date() + timedelta(days=100)).isoformat()
    saved = _paper(api, team.staff_a, vehicle["id"], "insurance", until, with_file=True).json()
    content = api.get(
        f"{API}/documents/{saved['document_id']}/content", headers=bearer(team.staff_b)
    )
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/jpeg"


def test_a_renewed_paper_replaces_the_old_one(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    old = (business_date() + timedelta(days=3)).isoformat()
    new = (business_date() + timedelta(days=368)).isoformat()
    _paper(api, team.staff_a, vehicle["id"], "insurance", old)
    _paper(api, team.staff_a, vehicle["id"], "insurance", new)
    detail = api.get(f"{API}/vehicles/{vehicle['id']}", headers=bearer(team.staff_a)).json()
    assert [(p["valid_until"], p["state"]) for p in detail["papers"]] == [(new, "ok")]
    history = api.get(
        f"{API}/vehicles/{vehicle['id']}/compliance", headers=bearer(team.staff_a)
    ).json()
    assert len(history) == 2


# --- Maintenance ----------------------------------------------------------------------------------


def test_maintenance_records(api: TestClient, team: Team) -> None:
    vehicle = _vehicle(api, team.staff_a)
    today = business_date()
    saved = api.post(
        f"{API}/vehicles/{vehicle['id']}/maintenance",
        json={
            "started_on": today.isoformat(),
            "ended_on": today.isoformat(),
            "description": "Demo service",
            "cost_paise": 150000,
        },
        headers=bearer(team.staff_a),
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["cost_paise"] == 150000
    assert saved.json()["recorded_by"]["id"] == team.staff_a_id
    listed = api.get(
        f"{API}/vehicles/{vehicle['id']}/maintenance", headers=bearer(team.staff_b)
    ).json()
    assert [m["description"] for m in listed] == ["Demo service"]


@pytest.mark.parametrize(
    "change",
    [
        {"cost_paise": -1},
        {"cost_paise": 12.5},
        {"ended_on": "2020-01-01"},
        {"description": "Aadhaar 1234 5678 9012"},
    ],
)
def test_maintenance_validation(api: TestClient, team: Team, change: dict[str, Any]) -> None:
    vehicle = _vehicle(api, team.staff_a)
    body: dict[str, Any] = {
        "started_on": business_date().isoformat(),
        "description": "Demo service",
    }
    body.update(change)
    response = api.post(
        f"{API}/vehicles/{vehicle['id']}/maintenance", json=body, headers=bearer(team.staff_a)
    )
    assert response.status_code == 422
    assert "5678" not in response.text
