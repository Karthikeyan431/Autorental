"""Pay requests and payments over HTTP (Week 6): permissions (D57 decision 1), the full
"send, record, confirm, approve, receipt" flow, idempotency, proof photos and reversals."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from app.core.permissions import Permission, api_route_access
from app.core.time import business_date
from tests.api.conftest import Team
from tests.api.driver_helpers import error_code, png_bytes
from tests.api.helpers import API, bearer
from tests.api.test_agreements_api import _given_an_auto

TEST_UPI_ID = "testautorentals@testbank"


def _setup(api: TestClient, team: Team, *, days_ago: int = 2) -> dict[str, Any]:
    """A UPI ID in Settings, staff A's driver with an auto for 3 days, rent accrued."""
    response = api.post(
        f"{API}/settings",
        headers=bearer(team.owner.token),
        json={"business_upi_id": TEST_UPI_ID, "upi_payee_name": "Test Auto Rentals"},
    )
    assert response.status_code in (200, 201), response.text
    given = _given_an_auto(api, team, days_ago=days_ago)
    assert api.post(f"{API}/jobs/accrue", headers=bearer(team.owner.token)).status_code == 200
    return given


def _record(
    api: TestClient,
    token: str,
    driver_id: int,
    amount: int,
    *,
    key: str,
    method: str = "cash",
    reference: str | None = None,
    proof: bool = True,
) -> Response:
    data: dict[str, Any] = {
        "driver_id": str(driver_id),
        "amount_paise": str(amount),
        "method": method,
        "received_on": business_date().isoformat(),
        "idempotency_key": key,
    }
    if reference is not None:
        data["reference"] = reference
    files = {"proof": ("proof.png", png_bytes(), "image/png")} if proof else None
    response: Response = api.post(f"{API}/payments", data=data, files=files, headers=bearer(token))
    return response


def _ledger_charge_ids(api: TestClient, token: str, driver_id: int) -> list[int]:
    ledger = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(token)).json()
    return [row["charge_id"] for row in ledger["rows"]]


def test_routes_declare_the_right_permissions(app: FastAPI) -> None:
    rules = {
        (method, route.path): route.rules[0]
        for route in api_route_access(app)
        for method in route.methods
    }
    expected = {
        ("POST", "/api/v1/pay-requests/generate"): Permission.PAYREQUESTS_SEND,
        ("POST", "/api/v1/pay-requests/{request_id}/sent"): Permission.PAYREQUESTS_SEND,
        ("POST", "/api/v1/payments"): Permission.PAYMENTS_RECORD,
        ("PUT", "/api/v1/payments/{payment_id}/allocations"): Permission.PAYMENTS_RECORD,
        ("POST", "/api/v1/payments/{payment_id}/allocations"): Permission.PAYMENTS_RECORD,
        ("POST", "/api/v1/payments/approve"): Permission.PAYMENTS_APPROVE,
        ("POST", "/api/v1/payments/{payment_id}/reject"): Permission.PAYMENTS_APPROVE,
        (
            "POST",
            "/api/v1/payments/{payment_id}/reversal-requests",
        ): Permission.ADJUSTMENTS_REQUEST,
        ("GET", "/api/v1/reversal-requests"): Permission.PAYMENTS_REVERSE_DECIDE,
        (
            "POST",
            "/api/v1/reversal-requests/{request_id}/decision",
        ): Permission.PAYMENTS_REVERSE_DECIDE,
        ("POST", "/api/v1/advance/adjustments"): Permission.ADJUSTMENTS_REQUEST,
        ("POST", "/api/v1/advance/refunds"): Permission.ADJUSTMENTS_REQUEST,
        ("POST", "/api/v1/advance/{transaction_id}/decision"): Permission.ADVANCE_DECIDE,
        ("GET", "/api/v1/advance/pending"): Permission.ADVANCE_DECIDE,
    }
    for key, permission in expected.items():
        assert rules[key].permission is permission, key


def test_send_record_confirm_approve_and_download_the_receipt(api: TestClient, team: Team) -> None:
    given = _setup(api, team)
    driver_id = given["driver"]["id"]

    generated = api.post(f"{API}/pay-requests/generate", headers=bearer(team.staff_a))
    assert generated.json() == {"created": 1, "superseded": 0, "unchanged": 0}
    again = api.post(f"{API}/pay-requests/generate", headers=bearer(team.staff_a)).json()
    assert again == {"created": 0, "superseded": 0, "unchanged": 1}

    (row,) = api.get(f"{API}/pay-requests", headers=bearer(team.staff_a)).json()
    assert row["amount_paise"] == 90_000
    assert row["whatsapp_url"].startswith("https://wa.me/919")
    assert "upi%3A%2F%2Fpay%3Fpa%3Dtestautorentals%40testbank" in row["whatsapp_url"]
    assert row["upi_link"].startswith("upi://pay?pa=testautorentals@testbank&pn=Test%20Auto")
    assert row["mdr_warning"] is False
    qr = api.get(f"{API}/pay-requests/{row['id']}/qr.png", headers=bearer(team.staff_a))
    assert qr.status_code == 200 and qr.content.startswith(b"\x89PNG")
    sent = api.post(f"{API}/pay-requests/{row['id']}/sent", headers=bearer(team.staff_a))
    assert sent.json()["send_count"] == 1

    created = _record(api, team.staff_a, driver_id, 90_000, key="api-key-flow-0001")
    assert created.status_code == 201, created.text
    payment = created.json()
    assert payment["status"] == "awaiting_approval"
    assert payment["allocations"] == [] and payment["days_confirmed"] is False
    assert payment["pay_request_id"] == row["id"]

    suggestion = api.get(
        f"{API}/payments/{payment['id']}/suggestion", headers=bearer(team.staff_a)
    ).json()
    assert [i["amount_paise"] for i in suggestion["items"]] == [30_000, 30_000, 30_000]
    confirmed = api.put(
        f"{API}/payments/{payment['id']}/allocations",
        json={
            "items": [
                {"rent_charge_id": i["rent_charge_id"], "amount_paise": i["amount_paise"]}
                for i in suggestion["items"]
            ]
        },
        headers=bearer(team.staff_a),
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["days_confirmed"] is True

    summary = api.get(f"{API}/payments/summary", headers=bearer(team.owner.token)).json()
    assert (summary["awaiting_count"], summary["awaiting_paise"]) == (1, 90_000)
    assert (summary["requests_today"], summary["sent_today"]) == (1, 1)

    assert (
        api.post(
            f"{API}/payments/approve", json={"ids": [payment["id"]]}, headers=bearer(team.staff_a)
        ).status_code
        == 403
    )
    (result,) = api.post(
        f"{API}/payments/approve", json={"ids": [payment["id"]]}, headers=bearer(team.owner.token)
    ).json()
    assert result["outcome"] == "approved"
    assert result["receipt_no"].startswith("RCPT/")

    ledger = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_a)).json()
    assert ledger["outstanding_paise"] == 0
    (paid,) = api.get(f"{API}/pay-requests", headers=bearer(team.staff_a)).json()
    assert paid["status"] == "paid"

    pdf = api.get(f"{API}/payments/{payment['id']}/receipt.pdf", headers=bearer(team.staff_a))
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    assert result["receipt_no"].encode() in pdf.content
    assert given["driver"]["full_name"].encode() in pdf.content


def test_a_non_manager_can_record_but_not_confirm_days_or_see_the_ledger(
    api: TestClient, team: Team
) -> None:
    given = _setup(api, team)
    driver_id = given["driver"]["id"]
    api.post(f"{API}/pay-requests/generate", headers=bearer(team.staff_a))

    created = _record(api, team.staff_b, driver_id, 30_000, key="api-key-office-0001")
    assert created.status_code == 201, created.text
    payment_id = created.json()["id"]
    seen = api.get(f"{API}/payments/{payment_id}", headers=bearer(team.staff_b)).json()
    assert seen["status"] == "awaiting_approval"
    assert seen["can_confirm_days"] is False

    charge_id = _ledger_charge_ids(api, team.staff_a, driver_id)[0]
    confirm = api.put(
        f"{API}/payments/{payment_id}/allocations",
        json={"items": [{"rent_charge_id": charge_id, "amount_paise": 30_000}]},
        headers=bearer(team.staff_b),
    )
    assert confirm.status_code == 403
    assert error_code(confirm) == "DAYS_CONFIRM_NOT_ALLOWED"
    suggestion = api.get(f"{API}/payments/{payment_id}/suggestion", headers=bearer(team.staff_b))
    assert suggestion.status_code == 403
    # D54: the ledger of a driver whose money you may not see is not found (404).
    ledger = api.get(f"{API}/drivers/{driver_id}/ledger", headers=bearer(team.staff_b))
    assert ledger.status_code == 404
    assert api.get(f"{API}/pay-requests", headers=bearer(team.staff_b)).json() == []

    # The owner's queue shows it, waiting for its days.
    queue = api.get(
        f"{API}/payments?status=awaiting_approval", headers=bearer(team.owner.token)
    ).json()
    assert [(p["id"], p["days_confirmed"]) for p in queue["items"]] == [(payment_id, False)]
    # The manager confirms the days.
    ok = api.put(
        f"{API}/payments/{payment_id}/allocations",
        json={"items": [{"rent_charge_id": charge_id, "amount_paise": 30_000}]},
        headers=bearer(team.staff_a),
    )
    assert ok.status_code == 200, ok.text


def test_a_payment_needs_a_proof_photo_and_a_double_tap_records_once(
    api: TestClient, team: Team
) -> None:
    given = _setup(api, team)
    driver_id = given["driver"]["id"]
    missing = _record(api, team.staff_a, driver_id, 30_000, key="api-key-proof-0001", proof=False)
    assert missing.status_code == 422
    assert error_code(missing) == "PROOF_REQUIRED"

    first = _record(api, team.staff_a, driver_id, 30_000, key="api-key-tap-0001")
    second = _record(api, team.staff_a, driver_id, 30_000, key="api-key-tap-0001")
    assert first.json()["id"] == second.json()["id"]
    listed = api.get(f"{API}/payments", headers=bearer(team.staff_a)).json()
    assert listed["total"] == 1

    upi = _record(
        api,
        team.staff_a,
        driver_id,
        30_000,
        key="api-key-upi-0001",
        method="upi",
        reference="TESTUTR000001",
    )
    assert upi.status_code == 201
    duplicate = _record(
        api,
        team.staff_a,
        driver_id,
        30_000,
        key="api-key-upi-0002",
        method="upi",
        reference="TESTUTR000001",
    )
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "DUPLICATE_REFERENCE"


def test_staff_request_a_reversal_and_only_the_owner_decides(api: TestClient, team: Team) -> None:
    given = _setup(api, team, days_ago=0)
    driver_id = given["driver"]["id"]
    payment_id = _record(api, team.staff_a, driver_id, 30_000, key="api-key-rev-0001").json()["id"]
    (charge_id,) = _ledger_charge_ids(api, team.staff_a, driver_id)
    api.put(
        f"{API}/payments/{payment_id}/allocations",
        json={"items": [{"rent_charge_id": charge_id, "amount_paise": 30_000}]},
        headers=bearer(team.staff_a),
    )
    api.post(
        f"{API}/payments/approve", json={"ids": [payment_id]}, headers=bearer(team.owner.token)
    )
    request = api.post(
        f"{API}/payments/{payment_id}/reversal-requests",
        json={"reason": "Recorded for the wrong day"},
        headers=bearer(team.staff_a),
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    assert api.get(f"{API}/reversal-requests", headers=bearer(team.staff_a)).status_code == 403
    denied = api.post(
        f"{API}/reversal-requests/{request_id}/decision",
        json={"decision": "approved"},
        headers=bearer(team.staff_a),
    )
    assert denied.status_code == 403
    decided = api.post(
        f"{API}/reversal-requests/{request_id}/decision",
        json={"decision": "approved"},
        headers=bearer(team.owner.token),
    )
    assert decided.status_code == 200, decided.text
    payment = api.get(f"{API}/payments/{payment_id}", headers=bearer(team.staff_a)).json()
    assert payment["status"] == "reversed" and payment["receipt_cancelled"] is True
    pdf = api.get(f"{API}/payments/{payment_id}/receipt.pdf", headers=bearer(team.staff_a))
    assert b"CANCELLED" in pdf.content


def test_the_proof_photo_follows_the_payment(api: TestClient, team: Team) -> None:
    given = _setup(api, team)
    driver_id = given["driver"]["id"]
    by_b = _record(api, team.staff_b, driver_id, 30_000, key="api-key-photo-0001").json()
    for token in (team.staff_b, team.staff_a, team.owner.token):
        response = api.get(f"{API}/documents/{by_b['proof_document_id']}", headers=bearer(token))
        assert response.status_code == 200
    # Staff B neither recorded this one nor manages the driver: not found (D57, D54).
    by_owner = _record(api, team.owner.token, driver_id, 30_000, key="api-key-photo-0002").json()
    for path in (f"documents/{by_owner['proof_document_id']}", f"payments/{by_owner['id']}"):
        assert api.get(f"{API}/{path}", headers=bearer(team.staff_b)).status_code == 404
