"""Agreements and rent over HTTP (Week 5): permissions, visibility (N1, D54, D56), the full
"give a driver an auto and fill the ledger" flow, the printed placeholder (Q13, D55) and the
signed copy."""

from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.permissions import Permission, api_route_access
from app.core.time import business_date
from tests.api.conftest import Team
from tests.api.driver_helpers import error_code, onboarded_driver, pdf_bytes
from tests.api.helpers import API, bearer


def _vehicle(api: TestClient, token: str, n: int = 1) -> dict[str, Any]:
    response = api.post(
        f"{API}/vehicles",
        json={"registration_number": f"TT 00 AG {n:04d}", "make": "Demo", "model": "Test 3W"},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _draft(
    api: TestClient, token: str, driver_id: int, vehicle_id: int, *, days_ago: int = 0
) -> Response:
    start = business_date() - timedelta(days=days_ago)
    response: Response = api.post(
        f"{API}/agreements",
        json={
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "start_date": start.isoformat(),
            "daily_rent_paise": 30000,
            "advance_required_paise": 200000,
        },
        headers=bearer(token),
    )
    return response


def _activate(api: TestClient, token: str, agreement_id: int) -> Response:
    response: Response = api.post(
        f"{API}/agreements/{agreement_id}/activate", headers=bearer(token)
    )
    return response


def _given_an_auto(api: TestClient, team: Team, *, days_ago: int = 3) -> dict[str, Any]:
    """Staff A registers and onboards a driver, registers an auto and activates an agreement."""
    driver = onboarded_driver(api, team.staff_a, 1)["driver"]
    vehicle = _vehicle(api, team.staff_a)
    draft = _draft(api, team.staff_a, driver["id"], vehicle["id"], days_ago=days_ago)
    assert draft.status_code == 201, draft.text
    active = _activate(api, team.staff_a, draft.json()["id"])
    assert active.status_code == 200, active.text
    return {"driver": driver, "vehicle": vehicle, "agreement": active.json()}


def test_routes_declare_the_right_permissions(app: FastAPI) -> None:
    rules = {
        (method, route.path): route.rules[0]
        for route in api_route_access(app)
        for method in route.methods
    }
    manage = Permission.AGREEMENTS_MANAGE
    for method, path in [
        ("POST", "/api/v1/agreements"),
        ("GET", "/api/v1/agreements/eligibility"),
        ("POST", "/api/v1/agreements/{agreement_id}/activate"),
        ("POST", "/api/v1/agreements/{agreement_id}/end"),
        ("POST", "/api/v1/agreements/{agreement_id}/cancel"),
        ("GET", "/api/v1/agreements/{agreement_id}/print"),
        ("POST", "/api/v1/agreements/{agreement_id}/signed-copy"),
    ]:
        assert rules[(method, path)].permission is manage, path
    assert (
        rules[("POST", "/api/v1/rent/charges/{charge_id}/adjustments")].permission
        is Permission.ADJUSTMENTS_REQUEST
    )
    assert (
        rules[("POST", "/api/v1/adjustments/{adjustment_id}/decision")].permission
        is Permission.ADJUSTMENTS_DECIDE
    )
    assert rules[("POST", "/api/v1/jobs/accrue")].permission is Permission.SETTINGS_MANAGE
    for path in ("/api/v1/agreements", "/api/v1/rent/overdue", "/api/v1/rent/summary"):
        assert rules[("GET", path)].kind == "authenticated"


def test_a_driver_gets_an_auto_and_the_ledger_fills(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    given = _given_an_auto(api, team, days_ago=3)
    agreement = given["agreement"]
    assert agreement["status"] == "active"
    assert agreement["agreement_no"].startswith("AG")
    assert agreement["vehicle"]["status"] == "rented"
    assert agreement["activated_by"]["id"] == team.staff_a_id

    staff_run = api.post(f"{API}/jobs/accrue", headers=bearer(team.staff_a))
    assert staff_run.status_code == 403
    run = api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token))
    assert run.status_code == 200, run.text
    assert run.json() == {"charges_created": 4, "agreements": 1}

    ledger = api.get(f"{API}/drivers/{given['driver']['id']}/ledger", headers=bearer(team.staff_a))
    assert ledger.status_code == 200, ledger.text
    body = ledger.json()
    assert len(body["rows"]) == 4  # three days ago to today
    assert body["totals"]["charge_paise"] == 120_000
    assert body["outstanding_paise"] == 120_000

    with Session(app_engine) as check:
        actions = set(
            check.scalars(select(AuditLog.action).where(AuditLog.entity_type == "agreement"))
        )
        assert {"agreement.created", "agreement.activated"} <= actions
        assert (
            check.scalars(select(AuditLog.actor_id).where(AuditLog.action == "rent.accrued")).one()
            == team.owner.id
        )


def test_the_same_auto_for_a_second_driver_is_refused_with_the_reason(
    api: TestClient, team: Team
) -> None:
    given = _given_an_auto(api, team)
    second = onboarded_driver(api, team.staff_a, 2)["driver"]
    refused = _draft(api, team.staff_a, second["id"], given["vehicle"]["id"])
    assert refused.status_code == 409
    assert error_code(refused) == "VEHICLE_NOT_AVAILABLE"


def test_activation_lists_every_reason(api: TestClient, team: Team, app_engine: Engine) -> None:
    driver = onboarded_driver(api, team.staff_a, 1)["driver"]
    vehicle = _vehicle(api, team.staff_a)
    draft = _draft(api, team.staff_a, driver["id"], vehicle["id"])
    restricted = api.post(
        f"{API}/drivers/{driver['id']}/restrictions",
        json={"reason": "Test restriction", "is_blocking": True},
        headers=bearer(team.owner.token),
    )
    assert restricted.status_code == 201, restricted.text
    refused = _activate(api, team.staff_a, draft.json()["id"])
    assert refused.status_code == 409
    assert error_code(refused) == "NOT_ELIGIBLE"
    details = refused.json()["error"]["details"]
    assert details["reasons"] == ["BLOCKING_RESTRICTION"]
    assert details["messages"]["BLOCKING_RESTRICTION"]


def test_the_live_eligibility_panel(api: TestClient, team: Team) -> None:
    driver = api.post(
        f"{API}/drivers",
        json={
            "full_name": "Test Driver 009",
            "mobile": "9000000009",
            "address": "Test address 009, Demo Nagar",
            "date_of_birth": "1990-01-01",
        },
        headers=bearer(team.staff_a),
    ).json()
    vehicle = _vehicle(api, team.staff_a)
    query = (
        f"driver_id={driver['id']}&vehicle_id={vehicle['id']}"
        f"&start_date={business_date().isoformat()}"
    )
    mine = api.get(f"{API}/agreements/eligibility?{query}", headers=bearer(team.staff_a)).json()
    assert mine["ok"] is False
    assert [r["code"] for r in mine["reasons"]] == [
        "IDENTITY_NOT_APPROVED",
        "LICENCE_NOT_APPROVED",
    ]
    # D56: staff B does not manage this driver and may not see its KYC.
    other = api.get(f"{API}/agreements/eligibility?{query}", headers=bearer(team.staff_b)).json()
    assert [r["code"] for r in other["reasons"]] == ["KYC_NOT_COMPLETE"]


def test_money_figures_follow_n1(api: TestClient, team: Team) -> None:
    given = _given_an_auto(api, team)
    api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token))
    driver_id = given["driver"]["id"]

    assert (
        api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_b)).status_code
        == 404
    )
    assert (
        api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.owner.token)).status_code
        == 200
    )

    own = api.get(f"{API}/rent/summary", headers=bearer(team.staff_b)).json()
    assert own["scope"] == "own"
    assert own["active_agreements"] == 0
    everything = api.get(f"{API}/rent/summary", headers=bearer(team.owner.token)).json()
    assert everything["scope"] == "all"
    assert everything["active_agreements"] == 1
    assert everything["rent_expected_today_paise"] == 30_000
    assert api.get(f"{API}/rent/overdue", headers=bearer(team.staff_b)).json() == []


def test_staff_request_an_adjustment_and_only_the_owner_decides(
    api: TestClient, team: Team
) -> None:
    given = _given_an_auto(api, team, days_ago=0)
    api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token))
    driver_id = given["driver"]["id"]
    (row,) = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_a)).json()[
        "rows"
    ]

    requested = api.post(
        f"{API}/rent/charges/{row['charge_id']}/adjustments",
        json={"amount_paise": -30000, "reason": "Auto off the road for repairs"},
        headers=bearer(team.staff_a),
    )
    assert requested.status_code == 201, requested.text
    adjustment = requested.json()
    assert adjustment["status"] == "pending"
    pending = api.get(f"{API}/adjustments", headers=bearer(team.owner.token)).json()
    assert [a["id"] for a in pending] == [adjustment["id"]]

    decision = {"decision": "approve", "reason": "Checked"}
    staff = api.post(
        f"{API}/adjustments/{adjustment['id']}/decision",
        json=decision,
        headers=bearer(team.staff_a),
    )
    assert staff.status_code == 403
    owner = api.post(
        f"{API}/adjustments/{adjustment['id']}/decision",
        json=decision,
        headers=bearer(team.owner.token),
    )
    assert owner.status_code == 200, owner.text
    ledger = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_a)).json()
    assert ledger["outstanding_paise"] == 0
    assert ledger["rows"][0]["status"] == "waived"


def test_a_zero_adjustment_is_refused(api: TestClient, team: Team) -> None:
    given = _given_an_auto(api, team, days_ago=0)
    api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token))
    (row,) = api.get(
        f"{API}/drivers/{given['driver']['id']}/ledger", headers=bearer(team.staff_a)
    ).json()["rows"]
    zero = api.post(
        f"{API}/rent/charges/{row['charge_id']}/adjustments",
        json={"amount_paise": 0, "reason": "Nothing"},
        headers=bearer(team.staff_a),
    )
    assert zero.status_code == 422


def test_ending_frees_the_auto(api: TestClient, team: Team) -> None:
    given = _given_an_auto(api, team, days_ago=2)
    today = business_date()
    ended = api.post(
        f"{API}/agreements/{given['agreement']['id']}/end",
        json={"end_date": today.isoformat(), "reason": "Returned"},
        headers=bearer(team.staff_b),  # any staff member with agreements.manage (D54)
    )
    assert ended.status_code == 200, ended.text
    body = ended.json()
    assert body["waivers_created"] == 0
    assert body["agreement"]["status"] == "ended"
    assert body["agreement"]["ended_by"]["id"] == team.staff_b_id
    assert body["agreement"]["vehicle"]["status"] == "available"
    assert body["agreement"]["vehicle_available_from"] == (today + timedelta(days=1)).isoformat()


def test_a_draft_can_be_cancelled_but_not_an_active_agreement(api: TestClient, team: Team) -> None:
    given = _given_an_auto(api, team)
    refused = api.post(
        f"{API}/agreements/{given['agreement']['id']}/cancel",
        json={"reason": "Changed mind"},
        headers=bearer(team.staff_a),
    )
    assert refused.status_code == 409
    assert error_code(refused) == "AGREEMENT_INVALID_TRANSITION"


def test_the_printed_agreement_is_a_placeholder_without_masked_fields(
    api: TestClient, team: Team
) -> None:
    given = _given_an_auto(api, team)
    response = api.get(
        f"{API}/agreements/{given['agreement']['id']}/print", headers=bearer(team.staff_a)
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    pdf = response.content
    assert pdf.startswith(b"%PDF")
    assert b"Test Driver 001" in pdf
    assert given["agreement"]["agreement_no"].encode() in pdf
    assert b"Rs. 300" in pdf
    assert b"Placeholder" in pdf
    # D55: no masked field (address, dates of birth, licence number).
    for secret in (b"Test address", b"1990", b"TEST-DL", b"TESTDL"):
        assert secret not in pdf


def test_the_signed_copy_is_for_the_owner_and_the_manager(api: TestClient, team: Team) -> None:
    given = _given_an_auto(api, team)
    agreement_id = given["agreement"]["id"]
    uploaded = api.post(
        f"{API}/agreements/{agreement_id}/signed-copy",
        files={"file": ("signed.pdf", pdf_bytes(), "application/pdf")},
        headers=bearer(team.staff_a),
    )
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["signed_document_id"]
    assert document_id is not None
    url = f"{API}/documents/{document_id}/content"
    assert api.get(url, headers=bearer(team.staff_a)).status_code == 200
    assert api.get(url, headers=bearer(team.owner.token)).status_code == 200
    assert api.get(url, headers=bearer(team.staff_b)).status_code == 404


def test_the_driver_timeline_shows_agreements_and_money_only_to_n1_viewers(
    api: TestClient, team: Team
) -> None:
    given = _given_an_auto(api, team, days_ago=0)
    api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token))
    driver_id = given["driver"]["id"]
    (row,) = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_a)).json()[
        "rows"
    ]
    api.post(
        f"{API}/rent/charges/{row['charge_id']}/adjustments",
        json={"amount_paise": -30000, "reason": "Auto off the road for repairs"},
        headers=bearer(team.staff_a),
    )

    def actions(token: str) -> set[str]:
        timeline = api.get(f"{API}/drivers/{driver_id}/timeline", headers=bearer(token))
        assert timeline.status_code == 200, timeline.text
        return {entry["action"] for entry in timeline.json()}

    manager = actions(team.staff_a)
    assert {"agreement.created", "agreement.activated", "charge_adjustment.requested"} <= manager
    other = actions(team.staff_b)
    assert "agreement.activated" in other
    assert "charge_adjustment.requested" not in other
