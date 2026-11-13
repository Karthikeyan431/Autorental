"""Week 4 KYC methods (rule 8; D47, D48, D49; docs/kyc.md).

* `uidai_app_attested` behind AADHAAR_APP_ATTEST_ENABLED (default off): with it off the
  endpoint is 404 and the method is not offered; with it on, attestation completes an identity
  check. "Signature not valid" is kept as evidence and approval is refused (D49).
* `uidai_qr` is not built (D48): never offered, even with its flag on (the refusal of a new
  attempt is test_kyc_api.py::test_uidai_qr_is_not_available_until_n13_is_answered).
* `parivahan_lookup`: a lookup record with a required screenshot; its validity dates feed
  eligibility.
* With both Aadhaar flags off, manual review plus the Parivahan lookup approves a driver.
* `demo`: development and test only, behind DEMO_VERIFIER_ENABLED; made-up details, no
  documents, marked simulated, a person still decides (Q25). Production refuses to start when a
  current check is simulated.
"""

import re
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from app.core.config import Settings, UnsafeConfigError
from app.core.time import business_date, utc_now
from app.main import create_app
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    IDENTITY_CHECKLIST,
    approve_identity,
    create_driver,
    decide,
    error_code,
    licence_details,
    record_consent,
    submit,
    submitted_identity,
    upload,
)
from tests.api.helpers import API, bearer
from tests.helpers import make_settings

ATTEST_CHECKLIST = {
    "photo_matches_person": True,
    "app_result_matches": True,
    "screenshot_masked": True,
}
PARIVAHAN_CHECKLIST = {
    "photo_matches_person": True,
    "lookup_matches_card": True,
    "classes_permitted": True,
    "valid_today": True,
}


def _start(api: TestClient, token: str, driver_id: int, check_type: str, method: str) -> Response:
    response: Response = api.post(
        f"{API}/drivers/{driver_id}/kyc/{check_type}/attempts",
        json={"method": method},
        headers=bearer(token),
    )
    return response


def _attest(api: TestClient, token: str, attempt_id: int, **overrides: Any) -> Response:
    body: dict[str, Any] = {
        "name_on_document": "Test Driver 001",
        "dob_or_yob": "1990",
        "id_last4": "0001",
        "signature_valid": True,
    }
    body.update(overrides)
    response: Response = api.post(
        f"{API}/kyc/attempts/{attempt_id}/uidai-app-attestation", json=body, headers=bearer(token)
    )
    return response


def _lookup_body(n: int = 1, **overrides: Any) -> dict[str, Any]:
    body = licence_details(n)
    body.update(
        lookup_status_text="ACTIVE (DEMO lookup record)",
        looked_up_at=(utc_now() - timedelta(minutes=5)).isoformat(),
    )
    body.update(overrides)
    return body


def _lookup(api: TestClient, token: str, attempt_id: int, **overrides: Any) -> Response:
    response: Response = api.post(
        f"{API}/kyc/attempts/{attempt_id}/parivahan-lookup",
        json=_lookup_body(**overrides),
        headers=bearer(token),
    )
    return response


def _kyc(api: TestClient, token: str, driver_id: int) -> dict[str, Any]:
    response = api.get(f"{API}/drivers/{driver_id}/kyc", headers=bearer(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


FlaggedClient = Callable[..., TestClient]


@pytest.fixture
def flagged_client(test_settings: Settings, app: FastAPI) -> Iterator[FlaggedClient]:
    """A client for a second app with some settings changed (same database, so the `team`
    users and tokens still work)."""
    apps: list[FastAPI] = []

    def factory(**changes: Any) -> TestClient:
        application = create_app(test_settings.model_copy(update=changes))
        apps.append(application)
        return TestClient(
            application,
            base_url="https://testserver",
            raise_server_exceptions=False,
            client=("127.0.0.1", 50000),
        )

    yield factory
    for application in apps:
        application.state.engine.dispose()


# --- Availability ---------------------------------------------------------------------------------


def test_both_aadhaar_flags_default_to_off() -> None:
    settings = make_settings()
    assert settings.AADHAAR_APP_ATTEST_ENABLED is False
    assert settings.AADHAAR_QR_INAPP_ENABLED is False


def test_uidai_qr_is_never_offered_even_with_its_flag_on() -> None:
    """D48: the decoder is not built, so the flag alone must not offer the method."""
    from app.modules.kyc.service import available_methods

    settings = make_settings(AADHAAR_QR_INAPP_ENABLED=True, AADHAAR_APP_ATTEST_ENABLED=True)
    assert "uidai_qr" not in available_methods(settings, "identity")


def test_default_flags_offer_manual_and_parivahan_only(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    methods = _kyc(api, team.staff_a, driver["id"])["available_methods"]
    assert methods == {"identity": ["manual"], "licence": ["manual", "parivahan_lookup"]}


def test_attestation_is_404_while_its_flag_is_off(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    refused = _start(api, team.staff_a, driver["id"], "identity", "uidai_app_attested")
    assert refused.status_code == 409
    assert error_code(refused) == "KYC_METHOD_NOT_AVAILABLE"
    attempt = _start(api, team.staff_a, driver["id"], "identity", "manual").json()["id"]
    assert _attest(api, team.staff_a, attempt).status_code == 404


def test_demo_is_not_offered_unless_enabled(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    response = _start(api, team.staff_a, driver["id"], "identity", "demo")
    assert response.status_code == 409
    assert error_code(response) == "KYC_METHOD_NOT_AVAILABLE"


# --- UIDAI app attestation (flag on) --------------------------------------------------------------


def test_attestation_completes_an_identity_check_with_its_flag_on(
    team: Team, flagged_client: FlaggedClient
) -> None:
    api = flagged_client(AADHAAR_APP_ATTEST_ENABLED=True)
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    assert _kyc(api, team.staff_a, driver["id"])["available_methods"]["identity"] == [
        "manual",
        "uidai_app_attested",
    ]
    attempt = _start(api, team.staff_a, driver["id"], "identity", "uidai_app_attested").json()["id"]
    saved = _attest(api, team.staff_a, attempt)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["method"] == "uidai_app_attested"
    assert body["evidence"]["uidai_app_signature_valid"] is True
    # No document is required; an optional masked screenshot may be added.
    shot = upload(api, team.staff_a, attempt, "attestation_screenshot")
    assert shot.status_code == 201, shot.text
    assert submit(api, team.staff_a, attempt).status_code == 200
    approved = decide(api, team.staff_a, attempt, checklist=ATTEST_CHECKLIST)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_attestation_saying_not_valid_is_kept_and_cannot_be_approved(
    team: Team, flagged_client: FlaggedClient, app_engine: Engine
) -> None:
    api = flagged_client(AADHAAR_APP_ATTEST_ENABLED=True)
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = _start(api, team.staff_a, driver["id"], "identity", "uidai_app_attested").json()["id"]
    assert _attest(api, team.staff_a, attempt, signature_valid=False).status_code == 200
    assert submit(api, team.staff_a, attempt).status_code == 200
    refused = decide(api, team.staff_a, attempt, checklist=ATTEST_CHECKLIST)
    assert refused.status_code == 409
    assert error_code(refused) == "UIDAI_SIGNATURE_NOT_VALID"
    with app_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT k.evidence ->> 'uidai_app_signature_valid', i.qr_signature_valid "
                "FROM kyc_checks k JOIN identity_details i ON i.kyc_check_id = k.id "
                "WHERE k.id = :id"
            ),
            {"id": attempt},
        ).one()
    assert stored == ("false", False)
    asked = decide(api, team.staff_a, attempt, "resubmit", reason="Signature not valid in app")
    assert asked.status_code == 200
    assert asked.json()["status"] == "resubmission_required"


def test_attestation_needs_the_right_attempt(team: Team, flagged_client: FlaggedClient) -> None:
    api = flagged_client(AADHAAR_APP_ATTEST_ENABLED=True)
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    manual = _start(api, team.staff_a, driver["id"], "identity", "manual").json()["id"]
    wrong = _attest(api, team.staff_a, manual)
    assert wrong.status_code == 409
    assert error_code(wrong) == "KYC_WRONG_METHOD"
    for bad in ("123412341234", "1234 1234 1234"):
        response = _attest(api, team.staff_a, manual, name_on_document=f"Test {bad}")
        assert response.status_code == 422
        assert bad not in response.text


def test_attestation_shows_the_honest_label(team: Team, flagged_client: FlaggedClient) -> None:
    api = flagged_client(AADHAAR_APP_ATTEST_ENABLED=True)
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = _start(api, team.staff_a, driver["id"], "identity", "uidai_app_attested").json()["id"]
    _attest(api, team.staff_a, attempt)
    body = api.get(f"{API}/kyc/attempts/{attempt}", headers=bearer(team.staff_a)).json()
    assert body["method_label"] == "Checked by staff with the UIDAI app"
    assert "Verified by system" not in str(body)


# --- Parivahan lookup record ----------------------------------------------------------------------


def _parivahan_attempt(api: TestClient, token: str, driver_id: int) -> int:
    response = _start(api, token, driver_id, "licence", "parivahan_lookup")
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_parivahan_needs_a_screenshot(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = _parivahan_attempt(api, team.staff_a, driver["id"])
    saved = _lookup(api, team.staff_a, attempt)
    assert saved.status_code == 200, saved.text
    details = saved.json()["licence_details"]
    assert details["lookup_status_text"] == "ACTIVE (DEMO lookup record)"
    assert details["looked_up_at"] is not None
    missing = submit(api, team.staff_a, attempt)
    assert missing.status_code == 409
    assert error_code(missing) == "KYC_INCOMPLETE"
    assert missing.json()["error"]["details"]["missing"] == ["lookup_screenshot"]
    assert upload(api, team.staff_a, attempt, "lookup_screenshot").status_code == 201
    assert submit(api, team.staff_a, attempt).status_code == 200


def test_parivahan_record_needs_status_and_time(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = _parivahan_attempt(api, team.staff_a, driver["id"])
    body = _lookup_body()
    del body["lookup_status_text"]
    response = api.post(
        f"{API}/kyc/attempts/{attempt}/parivahan-lookup", json=body, headers=bearer(team.staff_a)
    )
    assert response.status_code == 422
    future = _lookup(
        api, team.staff_a, attempt, looked_up_at=(utc_now() + timedelta(days=1)).isoformat()
    )
    assert future.status_code == 422


def test_parivahan_endpoint_needs_a_parivahan_attempt(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    manual = _start(api, team.staff_a, driver["id"], "licence", "manual").json()["id"]
    wrong = _lookup(api, team.staff_a, manual)
    assert wrong.status_code == 409
    assert error_code(wrong) == "KYC_WRONG_METHOD"
    parivahan = create_driver(api, team.staff_a, 2)
    record_consent(api, team.staff_a, parivahan["id"])
    attempt = _parivahan_attempt(api, team.staff_a, parivahan["id"])
    typed = api.put(
        f"{API}/kyc/attempts/{attempt}/licence-details",
        json=licence_details(2),
        headers=bearer(team.staff_a),
    )
    assert typed.status_code == 409
    assert error_code(typed) == "KYC_WRONG_METHOD"


def test_parivahan_validity_feeds_eligibility(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, submitted_identity(api, team.staff_a, driver["id"]))
    attempt = _parivahan_attempt(api, team.staff_a, driver["id"])
    until = business_date() + timedelta(days=200)
    assert (
        _lookup(
            api,
            team.staff_a,
            attempt,
            valid_until_transport=until.isoformat(),
            valid_until_non_transport=(business_date() + timedelta(days=4000)).isoformat(),
        ).status_code
        == 200
    )
    upload(api, team.staff_a, attempt, "lookup_screenshot")
    assert submit(api, team.staff_a, attempt).status_code == 200
    assert decide(api, team.staff_a, attempt, checklist=PARIVAHAN_CHECKLIST).status_code == 200
    eligibility = api.get(
        f"{API}/drivers/{driver['id']}/eligibility", headers=bearer(team.staff_a)
    ).json()
    assert eligibility["ok"] is True
    assert eligibility["licence_valid_until"] == until.isoformat()
    later = api.get(
        f"{API}/drivers/{driver['id']}/eligibility?on_date="
        f"{(until + timedelta(days=1)).isoformat()}",
        headers=bearer(team.staff_a),
    ).json()
    assert later["reasons"] == ["LICENCE_EXPIRED"]


def test_both_flags_off_manual_plus_parivahan_approves_a_driver(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, submitted_identity(api, team.staff_a, driver["id"]))
    attempt = _parivahan_attempt(api, team.staff_a, driver["id"])
    assert _lookup(api, team.staff_a, attempt).status_code == 200
    upload(api, team.staff_a, attempt, "lookup_screenshot")
    submit(api, team.staff_a, attempt)
    assert decide(api, team.staff_a, attempt, checklist=PARIVAHAN_CHECKLIST).status_code == 200
    eligibility = api.get(f"{API}/drivers/{driver['id']}/eligibility", headers=bearer(team.staff_a))
    assert eligibility.json()["ok"] is True


# --- Demo method (development and test only) ------------------------------------------------------


def test_demo_needs_no_documents_and_a_person_still_decides(
    team: Team, flagged_client: FlaggedClient
) -> None:
    api = flagged_client(DEMO_VERIFIER_ENABLED=True)
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    assert "demo" in _kyc(api, team.staff_a, driver["id"])["available_methods"]["identity"]
    started = _start(api, team.staff_a, driver["id"], "identity", "demo")
    assert started.status_code == 201, started.text
    attempt = started.json()
    assert attempt["is_simulated"] is True
    assert attempt["required_documents"] == []
    saved = api.put(
        f"{API}/kyc/attempts/{attempt['id']}/identity-details",
        json={
            "document_type": "masked_aadhaar",
            "id_last4": "0001",
            "name_on_document": "Test Driver 001 (DEMO)",
            "dob_or_yob": "1990",
        },
        headers=bearer(team.staff_a),
    )
    assert saved.status_code == 200
    submitted = submit(api, team.staff_a, attempt["id"])
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"  # never approved on its own (Q25)
    assert decide(api, team.staff_a, attempt["id"], checklist=IDENTITY_CHECKLIST).status_code == 200


def test_demo_is_never_available_in_production_settings() -> None:
    from app.modules.kyc.service import available_methods

    production = make_settings(APP_ENV="production")
    assert "demo" not in available_methods(production, "identity")
    assert "demo" not in available_methods(production, "licence")


# --- Production guard -----------------------------------------------------------------------------


def test_production_refuses_to_start_with_a_simulated_current_check(
    api: TestClient, team: Team, test_settings: Settings, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    production = make_settings(
        APP_ENV="production",
        DATABASE_URL=test_settings.DATABASE_URL,
        MIGRATION_DATABASE_URL=test_settings.MIGRATION_DATABASE_URL,
    )
    # A clean database starts.
    with TestClient(create_app(production)):
        pass
    with app_engine.begin() as connection:
        connection.execute(
            text("UPDATE kyc_checks SET is_simulated = true WHERE id = :id"), {"id": attempt}
        )
    with pytest.raises(UnsafeConfigError, match="simulated"), TestClient(create_app(production)):
        pass


def test_production_refuses_the_demo_flag() -> None:
    with pytest.raises(UnsafeConfigError, match="DEMO_VERIFIER_ENABLED"):
        create_app(make_settings(APP_ENV="production", DEMO_VERIFIER_ENABLED=True))


# --- Fixtures stay fake ---------------------------------------------------------------------------

_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")


def test_no_aadhaar_like_numbers_in_fixtures_or_seed() -> None:
    """No real Aadhaar number (or QR) in tests, fixtures or the seed (hard constraint 7).

    UIDAI never issues a number starting with 0 or 1, so the refusal probes the tests send
    (123412341234, 0000 1111 2222) cannot be real; the only other 12-digit runs allowed are
    fake +91 90000 mobile numbers."""
    repo = Path(__file__).resolve().parents[3]
    files = [
        *repo.joinpath("backend", "tests").rglob("*.py"),
        repo / "backend" / "app" / "cli" / "seed.py",
        *repo.joinpath("frontend", "src", "test").rglob("*.ts"),
        *repo.joinpath("frontend", "src").rglob("*.test.ts*"),
    ]
    offenders = []
    for path in files:
        for number in _TWELVE_DIGITS.findall(path.read_text(encoding="utf-8")):
            digits = re.sub(r"\D", "", number)
            if digits[0] in "01" or digits.startswith("9190000"):
                continue
            offenders.append((path.name, number))
    assert offenders == []
