"""KYC by manual review: consent first, separate checks (rule 7), decisions and reopen (rule 12),
who may see KYC (answer 1), duplicates, the Aadhaar guard and the queue (rule 9)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.modules.kyc.models import KycCheck, KycEvent
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    IDENTITY_CHECKLIST,
    LICENCE_CHECKLIST,
    approve_identity,
    create_driver,
    decide,
    error_code,
    new_attempt,
    record_consent,
    save_identity,
    save_licence,
    start_attempt,
    submit,
    submitted_identity,
    submitted_licence,
    upload,
)
from tests.api.helpers import API, bearer


def _kyc(api: TestClient, token: str, driver_id: int) -> dict:  # type: ignore[type-arg]
    response = api.get(f"{API}/drivers/{driver_id}/kyc", headers=bearer(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- Consent -------------------------------------------------------------------------------------


def test_a_kyc_attempt_without_consent_is_refused(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    for check_type in ("identity", "licence"):
        response = start_attempt(api, team.staff_a, driver["id"], check_type)
        assert response.status_code == 409
        assert error_code(response) == "CONSENT_REQUIRED"


def test_a_withdrawn_consent_blocks_new_attempts(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    consent = record_consent(api, team.staff_a, driver["id"])
    assert consent["captured_by"]["id"] == team.staff_a_id
    withdrawn = api.post(
        f"{API}/consents/{consent['id']}/withdraw",
        json={"reason": "Test withdrawal"},
        headers=bearer(team.staff_a),
    )
    assert withdrawn.status_code == 200, withdrawn.text
    response = start_attempt(api, team.staff_a, driver["id"], "identity")
    assert error_code(response) == "CONSENT_REQUIRED"


def test_consent_needs_a_known_purpose_and_method(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    response = api.post(
        f"{API}/drivers/{driver['id']}/consents",
        json={"purpose": "marketing", "notice_version": "v1", "method": "in_person_checkbox"},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 422


# --- Rule 7: separate checks with history --------------------------------------------------------


def test_approving_identity_leaves_the_licence_unapproved(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    identity = submitted_identity(api, team.staff_a, driver["id"])
    submitted_licence(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, identity)

    kyc = _kyc(api, team.staff_a, driver["id"])
    assert kyc["identity"]["status"] == "approved"
    assert kyc["licence"]["status"] == "submitted"
    eligibility = api.get(
        f"{API}/drivers/{driver['id']}/eligibility", headers=bearer(team.staff_a)
    ).json()
    assert eligibility["ok"] is False
    assert eligibility["reasons"] == ["LICENCE_NOT_APPROVED"]


def test_history_keeps_every_attempt_and_event(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    first = submitted_identity(api, team.staff_a, driver["id"])
    asked = decide(api, team.staff_a, first, "resubmit", reason="Test: blurred copy")
    assert asked.status_code == 200, asked.text
    second = submitted_identity(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, second)

    kyc = _kyc(api, team.staff_a, driver["id"])
    attempts = [(a["attempt_no"], a["status"], a["is_current"]) for a in kyc["history"]]
    assert sorted(attempts) == [
        (1, "resubmission_required", False),
        (2, "approved", True),
    ]
    with Session(app_engine) as session:
        events = session.scalars(
            select(KycEvent.to_status).where(KycEvent.kyc_check_id == first).order_by(KycEvent.id)
        ).all()
    assert events == ["draft", "submitted", "resubmission_required"]


# --- Decisions -----------------------------------------------------------------------------------


def test_staff_can_decide(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    response = decide(api, team.staff_a, attempt, checklist=IDENTITY_CHECKLIST)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"]["id"] == team.staff_a_id
    assert body["review_checklist"] == IDENTITY_CHECKLIST


def test_deciding_needs_kyc_decide(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    api.put(
        f"{API}/users/{team.staff_a_id}/permissions",
        json={"permissions": ["drivers.create", "drivers.edit_own"]},
        headers=bearer(team.owner.token),
    )
    response = decide(api, team.staff_a, attempt, checklist=IDENTITY_CHECKLIST)
    assert response.status_code == 403


def test_approval_needs_the_last4_only_tick(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    checklist = {**IDENTITY_CHECKLIST, "last4_only_visible": False}
    response = decide(api, team.staff_a, attempt, checklist=checklist)
    assert response.status_code == 409
    assert error_code(response) == "CHECKLIST_INCOMPLETE"
    assert "last4_only_visible" in response.json()["error"]["details"]["missing"]

    without = {k: v for k, v in IDENTITY_CHECKLIST.items() if k != "last4_only_visible"}
    assert error_code(decide(api, team.staff_a, attempt, checklist=without)) == (
        "CHECKLIST_INCOMPLETE"
    )


def test_licence_approval_needs_its_checklist(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_licence(api, team.staff_a, driver["id"])
    partial = {**LICENCE_CHECKLIST, "classes_permitted": False}
    assert error_code(decide(api, team.staff_a, attempt, checklist=partial)) == (
        "CHECKLIST_INCOMPLETE"
    )
    ok = decide(api, team.staff_a, attempt, checklist=LICENCE_CHECKLIST)
    assert ok.status_code == 200


def test_reject_and_resubmit_need_a_reason(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    for decision in ("reject", "resubmit"):
        response = decide(api, team.staff_a, attempt, decision)
        assert response.status_code == 422, decision
        assert error_code(response) == "REASON_REQUIRED"
    rejected = decide(api, team.staff_a, attempt, "reject", reason="Test: wrong person")
    assert rejected.status_code == 200
    assert rejected.json()["decision_reason"] == "Test: wrong person"


def test_a_draft_cannot_be_decided(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")
    response = decide(api, team.staff_a, attempt, checklist=IDENTITY_CHECKLIST)
    assert response.status_code == 409
    assert error_code(response) == "KYC_INVALID_TRANSITION"


def test_submit_needs_details_and_documents(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    identity = new_attempt(api, team.staff_a, driver["id"], "identity")
    response = submit(api, team.staff_a, identity)
    assert error_code(response) == "KYC_INCOMPLETE"
    assert save_identity(api, team.staff_a, identity).status_code == 200
    assert error_code(submit(api, team.staff_a, identity)) == "KYC_INCOMPLETE"  # no document

    licence = new_attempt(api, team.staff_a, driver["id"], "licence")
    assert save_licence(api, team.staff_a, licence).status_code == 200
    assert upload(api, team.staff_a, licence, "licence_front").status_code == 201
    missing_back = submit(api, team.staff_a, licence)
    assert error_code(missing_back) == "KYC_INCOMPLETE"
    assert "licence_back" in missing_back.json()["error"]["details"]["missing"]


def test_a_submitted_attempt_is_no_longer_editable(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    assert error_code(save_identity(api, team.staff_a, attempt)) == "ATTEMPT_NOT_EDITABLE"
    assert error_code(upload(api, team.staff_a, attempt, "id_back")) == "ATTEMPT_NOT_EDITABLE"


def test_uidai_qr_is_not_available_until_n13_is_answered(api: TestClient, team: Team) -> None:
    """D48: the in-app Secure QR decoder is not built; Week 4 adds other methods (see
    test_kyc_methods.py), but a new uidai_qr attempt is still refused."""
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    response = api.post(
        f"{API}/drivers/{driver['id']}/kyc/identity/attempts",
        json={"method": "uidai_qr"},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 409
    assert error_code(response) == "KYC_METHOD_NOT_AVAILABLE"


def test_only_one_open_attempt_per_check(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    new_attempt(api, team.staff_a, driver["id"], "identity")
    again = start_attempt(api, team.staff_a, driver["id"], "identity")
    assert again.status_code == 409
    assert error_code(again) == "KYC_ATTEMPT_OPEN"


# --- Answer 2: resubmission versus reject ---------------------------------------------------------


def test_resubmission_lets_staff_start_a_new_attempt(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    decide(api, team.staff_a, attempt, "resubmit", reason="Test: unreadable")
    response = start_attempt(api, team.staff_a, driver["id"], "identity")
    assert response.status_code == 201, response.text
    assert response.json()["attempt_no"] == 2
    assert response.json()["status"] == "draft"


def test_rejected_and_approved_change_only_through_an_owner_reopen(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    identity = submitted_identity(api, team.staff_a, driver["id"])
    decide(api, team.staff_a, identity, "reject", reason="Test: final")
    licence = submitted_licence(api, team.staff_a, driver["id"])
    decide(api, team.staff_a, licence, checklist=LICENCE_CHECKLIST)
    for check_type in ("identity", "licence"):
        response = start_attempt(api, team.staff_a, driver["id"], check_type)
        assert response.status_code == 409, check_type
        assert error_code(response) == "KYC_REOPEN_REQUIRED"


# --- Rule 12: reopen ------------------------------------------------------------------------------


def test_staff_cannot_reopen(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, attempt)
    response = api.post(
        f"{API}/kyc/attempts/{attempt}/reopen",
        json={"reason": "Test"},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 403


def test_owner_reopen_creates_attempt_2_and_keeps_attempt_1(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    first = submitted_identity(api, team.staff_a, driver["id"])
    approve_identity(api, team.staff_a, first)
    with Session(app_engine) as session:
        events_before = session.scalars(
            select(KycEvent.to_status).where(KycEvent.kyc_check_id == first).order_by(KycEvent.id)
        ).all()

    missing_reason = api.post(
        f"{API}/kyc/attempts/{first}/reopen", json={}, headers=bearer(team.owner.token)
    )
    assert missing_reason.status_code == 422

    response = api.post(
        f"{API}/kyc/attempts/{first}/reopen",
        json={"reason": "Test: owner second look"},
        headers=bearer(team.owner.token),
    )
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["attempt_no"] == 2
    assert second["status"] == "under_review"
    assert second["is_current"] is True
    assert second["reopened_from_id"] == first
    assert second["identity_details"]["id_last4"] == "0001"  # carried over for the review

    with Session(app_engine) as session:
        old = session.get(KycCheck, first)
        assert old is not None
        assert old.status == "approved"
        assert old.is_current is False
        events_after = session.scalars(
            select(KycEvent.to_status).where(KycEvent.kyc_check_id == first).order_by(KycEvent.id)
        ).all()
    assert events_after == events_before

    kyc = _kyc(api, team.owner.token, driver["id"])
    assert kyc["identity"]["id"] == second["id"]
    assert len(kyc["history"]) == 2
    eligibility = api.get(
        f"{API}/drivers/{driver['id']}/eligibility", headers=bearer(team.owner.token)
    ).json()
    assert "IDENTITY_NOT_APPROVED" in eligibility["reasons"]

    # The reopened attempt can be decided again.
    again = decide(api, team.staff_a, second["id"], checklist=IDENTITY_CHECKLIST)
    assert again.status_code == 200, again.text


def test_reopen_works_only_on_approved_or_rejected(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    response = api.post(
        f"{API}/kyc/attempts/{attempt}/reopen",
        json={"reason": "Test"},
        headers=bearer(team.owner.token),
    )
    assert response.status_code == 409
    assert error_code(response) == "KYC_INVALID_TRANSITION"


# --- Answer 1: who sees KYC -----------------------------------------------------------------------


def test_other_staff_get_404_for_kyc(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    other = bearer(team.staff_b)

    assert api.get(f"{API}/drivers/{driver['id']}/kyc", headers=other).status_code == 404
    assert api.get(f"{API}/kyc/attempts/{attempt}", headers=other).status_code == 404
    assert decide(api, team.staff_b, attempt, checklist=IDENTITY_CHECKLIST).status_code == 404
    assert start_attempt(api, team.staff_b, driver["id"], "licence").status_code == 404
    consent = api.post(
        f"{API}/drivers/{driver['id']}/consents",
        json={"purpose": "kyc", "notice_version": "v1", "method": "in_person_checkbox"},
        headers=other,
    )
    assert consent.status_code == 404

    # The owner and staff with drivers.edit_any can see it; from Week 4 only the owner and the
    # current manager decide (D46), so edit_any staff get 403 KYC_DECIDE_NOT_ALLOWED.
    assert api.get(
        f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.owner.token)
    ).status_code == (200)
    api.put(
        f"{API}/users/{team.staff_b_id}/permissions",
        json={"permissions": ["drivers.edit_own", "drivers.edit_any", "kyc.decide"]},
        headers=bearer(team.owner.token),
    )
    assert api.get(f"{API}/drivers/{driver['id']}/kyc", headers=other).status_code == 200
    refused = decide(api, team.staff_b, attempt, checklist=IDENTITY_CHECKLIST)
    assert refused.status_code == 403
    assert error_code(refused) == "KYC_DECIDE_NOT_ALLOWED"
    assert decide(api, team.owner.token, attempt, checklist=IDENTITY_CHECKLIST).status_code == 200


def test_a_new_manager_gains_kyc_access_and_the_old_one_loses_it(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test"},
        headers=bearer(team.owner.token),
    )
    assert api.get(
        f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.staff_a)
    ).status_code == (404)
    assert api.get(
        f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.staff_b)
    ).status_code == (200)


# --- Duplicates and the Aadhaar guard -------------------------------------------------------------


def test_a_duplicate_licence_number_is_refused(api: TestClient, team: Team) -> None:
    first = create_driver(api, team.staff_a, 1)
    record_consent(api, team.staff_a, first["id"])
    submitted_licence(api, team.staff_a, first["id"], 1)

    second = create_driver(api, team.staff_b, 2)
    record_consent(api, team.staff_b, second["id"])
    attempt = new_attempt(api, team.staff_b, second["id"], "licence")
    for variant in ("TEST-DL-0001", "test dl 0001", "TESTDL0001"):
        response = save_licence(api, team.staff_b, attempt, 2, licence_number=variant)
        assert response.status_code == 409, variant
        assert error_code(response) == "LICENCE_TAKEN"


def test_the_licence_number_is_never_returned_in_full(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_licence(api, team.staff_a, driver["id"])
    body = api.get(f"{API}/kyc/attempts/{attempt}", headers=bearer(team.staff_a)).json()
    details = body["licence_details"]
    assert "licence_number" not in details
    assert details["licence_number_masked"].endswith("0001")
    assert "TESTDL0001" not in str(body)


def test_no_12_digit_number_is_accepted_in_identity_fields(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")
    for field, value in (
        ("id_last4", "123412341234"),
        ("id_last4", "12345"),
        ("id_last4", "12a4"),
        ("name_on_document", "Test 1234 5678 9012"),
        ("name_on_document", "Test 1234-5678-9012"),
        ("dob_or_yob", "123456789012"),
    ):
        response = save_identity(api, team.staff_a, attempt, **{field: value})
        assert response.status_code == 422, (field, value)


def test_decision_reasons_refuse_aadhaar_like_numbers(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = submitted_identity(api, team.staff_a, driver["id"])
    response = decide(api, team.staff_a, attempt, "reject", reason="Full number 123412341234")
    assert response.status_code == 422


def test_identity_document_type_must_be_accepted(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")
    response = save_identity(api, team.staff_a, attempt, document_type="voter_id")
    assert response.status_code == 409
    assert error_code(response) == "ID_TYPE_NOT_ACCEPTED"


# --- Rule 9: the queue ----------------------------------------------------------------------------


def _queue(api: TestClient, token: str, bucket: str) -> list[tuple[int, str]]:
    response = api.get(f"{API}/kyc/queue?bucket={bucket}", headers=bearer(token))
    assert response.status_code == 200, response.text
    return [(item["driver"]["id"], item["check_type"]) for item in response.json()["items"]]


def test_a_new_driver_appears_in_the_queue_and_counts_match(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    owner = team.owner.token
    assert set(_queue(api, owner, "pending")) == {
        (driver["id"], "identity"),
        (driver["id"], "licence"),
    }
    record_consent(api, team.staff_a, driver["id"])
    submitted_identity(api, team.staff_a, driver["id"])
    assert _queue(api, owner, "under_review") == [(driver["id"], "identity")]
    assert _queue(api, owner, "pending") == [(driver["id"], "licence")]

    counts = api.get(f"{API}/kyc/queue/counts", headers=bearer(owner)).json()
    for bucket in ("pending", "under_review", "resubmission", "rejected", "expiring"):
        assert counts[bucket] == len(_queue(api, owner, bucket)), bucket


def test_staff_queue_shows_only_drivers_they_can_decide_on(api: TestClient, team: Team) -> None:
    mine = create_driver(api, team.staff_a, 1)
    create_driver(api, team.staff_b, 2)
    rows = _queue(api, team.staff_a, "pending")
    assert {driver_id for driver_id, _ in rows} == {mine["id"]}
    counts = api.get(f"{API}/kyc/queue/counts", headers=bearer(team.staff_a)).json()
    assert counts["pending"] == 2
