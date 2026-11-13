"""Masked identity fields (D45, D46; N15 to N19).

* Masked by default in every driver, list and KYC response; full values only from
  `POST /drivers/{id}/reveal`, for the owner and the driver's current manager.
* Each reveal writes one `driver.field_revealed` audit entry (field name, never the value) that
  shows in the driver's Activity tab; reveals are rate-limited per user.
* KYC document images, KYC decisions and KYC capture: owner and current manager only.
* Only the owner and the current manager edit masked fields; a blank value keeps the current one.
* The address and both dates of birth are encrypted at rest.
* Audit entries, KYC history, the timeline and logs never hold a masked value (addition A).
"""

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from app.core.logging import JsonFormatter
from tests.api.conftest import STAFF_A_MOBILE, FakeClock, Team
from tests.api.driver_helpers import (
    IDENTITY_CHECKLIST,
    LICENCE_CHECKLIST,
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
from tests.api.helpers import API, bearer, staff_token

# Distinctive fake values, searched for everywhere they must not appear.
ADDRESS = "Test address QZX-4471, Demo Nagar"
NEW_ADDRESS = "Test address QZX-9902, Demo Puram"
DOB = "1987-03-04"
NEW_DOB = "1988-05-06"
LICENCE_NO = "TEST-DL-7741"
LICENCE_NO_NORMALISED = "TESTDL7741"
LICENCE_DOB = "1986-07-08"
ID_DOB = "1985-09-10"
GENDER = "TestGenderQZX"
SECRETS = [
    ADDRESS,
    NEW_ADDRESS,
    DOB,
    NEW_DOB,
    LICENCE_NO,
    LICENCE_NO_NORMALISED,
    LICENCE_DOB,
    ID_DOB,
    GENDER,
]


def _leaks(text_value: str) -> list[str]:
    return [s for s in SECRETS if s in text_value]


def _grant_edit_any(api: TestClient, team: Team) -> None:
    response = api.put(
        f"{API}/users/{team.staff_b_id}/permissions",
        json={
            "permissions": ["drivers.create", "drivers.edit_own", "drivers.edit_any", "kyc.decide"]
        },
        headers=bearer(team.owner.token),
    )
    assert response.status_code == 200, response.text


def _reveal(
    api: TestClient, token: str, driver_id: int, field: str, attempt_id: int | None = None
) -> Response:
    body: dict[str, Any] = {"field": field}
    if attempt_id is not None:
        body["attempt_id"] = attempt_id
    response: Response = api.post(
        f"{API}/drivers/{driver_id}/reveal", json=body, headers=bearer(token)
    )
    return response


def _full_driver(api: TestClient, team: Team) -> dict[str, Any]:
    """A driver registered by staff A with every masked value set, both checks submitted."""
    driver = create_driver(api, team.staff_a, 1, address=ADDRESS, date_of_birth=DOB)
    record_consent(api, team.staff_a, driver["id"])
    identity = new_attempt(api, team.staff_a, driver["id"], "identity")
    assert (
        save_identity(api, team.staff_a, identity, dob_or_yob=ID_DOB, gender=GENDER).status_code
        == 200
    )
    assert upload(api, team.staff_a, identity, "id_front").status_code == 201
    assert submit(api, team.staff_a, identity).status_code == 200
    licence = new_attempt(api, team.staff_a, driver["id"], "licence")
    saved = save_licence(
        api, team.staff_a, licence, licence_number=LICENCE_NO, date_of_birth=LICENCE_DOB
    )
    assert saved.status_code == 200, saved.text
    assert upload(api, team.staff_a, licence, "licence_front").status_code == 201
    assert upload(api, team.staff_a, licence, "licence_back").status_code == 201
    assert submit(api, team.staff_a, licence).status_code == 200
    return {"driver": driver, "identity": identity, "licence": licence}


# --- Masked by default ----------------------------------------------------------------------------


def test_driver_responses_are_masked_by_default(api: TestClient, team: Team) -> None:
    case = _full_driver(api, team)
    driver_id = case["driver"]["id"]
    assert not _leaks(str(case["driver"]))
    for token in (team.owner.token, team.staff_a, team.staff_b):
        detail = api.get(f"{API}/drivers/{driver_id}", headers=bearer(token))
        assert detail.status_code == 200
        body = detail.json()
        assert "address" not in body and "date_of_birth" not in body
        assert set(body["masked_fields"]) == {"address", "date_of_birth"}
        assert not _leaks(detail.text)
        listed = api.get(f"{API}/drivers", headers=bearer(token))
        assert not _leaks(listed.text)
    kyc = api.get(f"{API}/drivers/{driver_id}/kyc", headers=bearer(team.staff_a))
    assert kyc.status_code == 200
    assert not _leaks(kyc.text)
    identity = kyc.json()["identity"]["identity_details"]
    assert "dob_or_yob" not in identity and "gender" not in identity
    assert set(identity["masked_fields"]) == {"id_dob_or_yob", "id_gender"}
    licence = kyc.json()["licence"]["licence_details"]
    assert "date_of_birth" not in licence
    assert set(licence["masked_fields"]) == {"licence_number", "licence_date_of_birth"}
    assert licence["licence_number_masked"].endswith("7741")


def test_can_reveal_is_true_only_for_the_owner_and_the_current_manager(
    api: TestClient, team: Team
) -> None:
    driver = create_driver(api, team.staff_a)
    _grant_edit_any(api, team)
    url = f"{API}/drivers/{driver['id']}"
    assert api.get(url, headers=bearer(team.owner.token)).json()["can_reveal"] is True
    assert api.get(url, headers=bearer(team.staff_a)).json()["can_reveal"] is True
    assert api.get(url, headers=bearer(team.staff_b)).json()["can_reveal"] is False


# --- Reveal ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("address", ADDRESS),
        ("date_of_birth", DOB),
        ("licence_number", LICENCE_NO_NORMALISED),
        ("licence_date_of_birth", LICENCE_DOB),
        ("id_dob_or_yob", ID_DOB),
        ("id_gender", GENDER),
    ],
)
def test_owner_and_current_manager_can_reveal_each_field(
    api: TestClient, team: Team, field: str, expected: str
) -> None:
    case = _full_driver(api, team)
    for token in (team.owner.token, team.staff_a):
        response = _reveal(api, token, case["driver"]["id"], field)
        assert response.status_code == 200, response.text
        assert response.json() == {"field": field, "value": expected}
        assert response.headers["cache-control"] == "no-store"


def test_other_staff_get_403_even_with_edit_any(api: TestClient, team: Team) -> None:
    case = _full_driver(api, team)
    driver_id = case["driver"]["id"]
    for field in ("address", "licence_number"):
        plain = _reveal(api, team.staff_b, driver_id, field)
        assert plain.status_code == 403
        assert error_code(plain) == "REVEAL_NOT_ALLOWED"
    _grant_edit_any(api, team)
    with_edit_any = _reveal(api, team.staff_b, driver_id, "address")
    assert with_edit_any.status_code == 403
    assert error_code(with_edit_any) == "REVEAL_NOT_ALLOWED"
    assert not _leaks(with_edit_any.text)


def test_unknown_driver_or_field_gets_404(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    assert _reveal(api, team.owner.token, 999999, "address").status_code == 404
    assert _reveal(api, team.owner.token, driver["id"], "mobile").status_code == 404
    # No licence yet: nothing to reveal.
    assert _reveal(api, team.owner.token, driver["id"], "licence_number").status_code == 404


def test_reveal_follows_the_manager_change_at_once(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a, address=ADDRESS)
    moved = api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test"},
        headers=bearer(team.owner.token),
    )
    assert moved.status_code == 200
    old = _reveal(api, team.staff_a, driver["id"], "address")
    assert old.status_code == 403
    assert error_code(old) == "REVEAL_NOT_ALLOWED"
    new = _reveal(api, team.staff_b, driver["id"], "address")
    assert new.status_code == 200
    assert new.json()["value"] == ADDRESS


def test_each_reveal_writes_one_audit_entry_shown_in_the_activity_tab(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a, address=ADDRESS)
    assert _reveal(api, team.staff_a, driver["id"], "address").status_code == 200
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT actor_id, entity_id, after::text FROM audit_logs "
                "WHERE action = 'driver.field_revealed'"
            )
        ).all()
    assert len(rows) == 1
    actor_id, entity_id, after = rows[0]
    assert (actor_id, entity_id) == (team.staff_a_id, driver["id"])
    assert '"field": "address"' in after
    assert not _leaks(after)

    timeline = api.get(f"{API}/drivers/{driver['id']}/timeline", headers=bearer(team.staff_b))
    assert timeline.status_code == 200
    revealed = [e for e in timeline.json() if e["action"] == "driver.field_revealed"]
    assert len(revealed) == 1
    assert revealed[0]["after"] == {"field": "address"}
    assert not _leaks(timeline.text)


def test_refused_reveals_write_no_reveal_entry(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    driver = create_driver(api, team.staff_a, address=ADDRESS)
    assert _reveal(api, team.staff_b, driver["id"], "address").status_code == 403
    with app_engine.connect() as connection:
        count = connection.scalar(
            text(
                "SELECT count(*) FROM audit_logs WHERE action LIKE 'driver.reveal%' "
                "OR action = 'driver.field_revealed'"
            )
        )
    assert count == 0


def test_reveals_are_rate_limited_per_user_from_the_setting(
    api: TestClient, team: Team, app_engine: Engine, clock: FakeClock
) -> None:
    changed = api.post(
        f"{API}/settings", json={"reveal_limit_per_hour": 3}, headers=bearer(team.owner.token)
    )
    assert changed.status_code in (200, 201), changed.text
    driver = create_driver(api, team.staff_a, address=ADDRESS)
    for _ in range(3):
        assert _reveal(api, team.staff_a, driver["id"], "address").status_code == 200
    for _ in range(3):
        limited = _reveal(api, team.staff_a, driver["id"], "address")
        assert limited.status_code == 429
        assert error_code(limited) == "REVEAL_RATE_LIMITED"
        assert not _leaks(limited.text)
    # The owner has their own allowance.
    assert _reveal(api, team.owner.token, driver["id"], "address").status_code == 200

    with app_engine.connect() as connection:
        actions = connection.execute(
            text(
                "SELECT action, count(*) FROM audit_logs WHERE actor_id = :id "
                "AND action LIKE 'driver.%reveal%' GROUP BY action"
            ),
            {"id": team.staff_a_id},
        ).all()
    assert dict(actions) == {"driver.field_revealed": 3, "driver.reveal_rate_limited": 1}

    clock.advance(minutes=61)
    fresh = staff_token(api, STAFF_A_MOBILE)  # the 15-minute access token has expired
    assert _reveal(api, fresh, driver["id"], "address").status_code == 200


def test_the_default_reveal_limit_is_30(api: TestClient, team: Team) -> None:
    current = api.get(f"{API}/settings/current", headers=bearer(team.owner.token))
    assert current.json()["reveal_limit_per_hour"] == 30


def test_reveal_of_an_older_attempt_must_belong_to_the_driver(api: TestClient, team: Team) -> None:
    case = _full_driver(api, team)
    other = create_driver(api, team.staff_a, 2)
    response = _reveal(api, team.owner.token, other["id"], "licence_number", case["licence"])
    assert response.status_code == 404


# --- Editing masked fields (N17) ------------------------------------------------------------------


def test_only_owner_and_current_manager_edit_masked_fields(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a, address=ADDRESS, date_of_birth=DOB)
    url = f"{API}/drivers/{driver['id']}"
    _grant_edit_any(api, team)

    for field, value in (("address", NEW_ADDRESS), ("date_of_birth", NEW_DOB)):
        refused = api.patch(url, json={field: value}, headers=bearer(team.staff_b))
        assert refused.status_code == 403, field
        assert error_code(refused) == "FIELD_NOT_EDITABLE"
        assert not _leaks(refused.text)

    other = api.patch(
        url, json={"emergency_name": "Test Contact 999"}, headers=bearer(team.staff_b)
    )
    assert other.status_code == 200, other.text

    mine = api.patch(url, json={"address": NEW_ADDRESS}, headers=bearer(team.staff_a))
    assert mine.status_code == 200, mine.text
    assert not _leaks(mine.text)
    assert _reveal(api, team.owner.token, driver["id"], "address").json()["value"] == NEW_ADDRESS
    owner = api.patch(url, json={"date_of_birth": NEW_DOB}, headers=bearer(team.owner.token))
    assert owner.status_code == 200
    assert _reveal(api, team.owner.token, driver["id"], "date_of_birth").json()["value"] == NEW_DOB


def test_a_blank_masked_field_keeps_the_current_value(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a, address=ADDRESS, date_of_birth=DOB)
    url = f"{API}/drivers/{driver['id']}"
    for body in (
        {"address": "", "date_of_birth": ""},
        {"address": None, "date_of_birth": None},
        {"address": "   "},
    ):
        response = api.patch(url, json=body, headers=bearer(team.staff_a))
        assert response.status_code == 200, (body, response.text)
    assert _reveal(api, team.staff_a, driver["id"], "address").json()["value"] == ADDRESS
    assert _reveal(api, team.staff_a, driver["id"], "date_of_birth").json()["value"] == DOB


def test_the_date_of_birth_must_still_be_in_the_past(api: TestClient, team: Team) -> None:
    tomorrow = "2999-01-01"
    create = api.post(
        f"{API}/drivers",
        json={
            "full_name": "Test Driver 001",
            "mobile": "9000000001",
            "address": ADDRESS,
            "date_of_birth": tomorrow,
        },
        headers=bearer(team.staff_a),
    )
    assert create.status_code == 422
    driver = create_driver(api, team.staff_a, 2)
    edit = api.patch(
        f"{API}/drivers/{driver['id']}",
        json={"date_of_birth": tomorrow},
        headers=bearer(team.staff_a),
    )
    assert edit.status_code == 422


# --- Documents, decisions and capture (N16, D46) --------------------------------------------------


def test_document_images_are_for_owner_and_current_manager(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")
    document_id = upload(api, team.staff_a, attempt, "id_front").json()["id"]
    url = f"{API}/documents/{document_id}/content"
    assert api.get(url, headers=bearer(team.owner.token)).status_code == 200
    assert api.get(url, headers=bearer(team.staff_a)).status_code == 200
    _grant_edit_any(api, team)
    assert api.get(url, headers=bearer(team.staff_b)).status_code == 404
    assert (
        api.get(f"{API}/documents/{document_id}", headers=bearer(team.staff_b)).status_code == 404
    )

    api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test"},
        headers=bearer(team.owner.token),
    )
    assert api.get(url, headers=bearer(team.staff_a)).status_code == 404
    assert api.get(url, headers=bearer(team.staff_b)).status_code == 200


def test_driver_photo_stays_visible_to_all_staff(api: TestClient, team: Team) -> None:
    from tests.api.driver_helpers import jpeg_bytes

    driver = create_driver(api, team.staff_a)
    photo = api.post(
        f"{API}/drivers/{driver['id']}/photo",
        files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")},
        headers=bearer(team.staff_a),
    )
    assert photo.status_code == 200
    document_id = photo.json()["photo_document_id"]
    assert (
        api.get(f"{API}/documents/{document_id}/content", headers=bearer(team.staff_b)).status_code
        == 200
    )


def test_kyc_decisions_are_for_owner_and_current_manager(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    identity = submitted_identity(api, team.staff_a, driver["id"])
    licence = submitted_licence(api, team.staff_a, driver["id"])
    _grant_edit_any(api, team)

    refused = decide(api, team.staff_b, identity, checklist=IDENTITY_CHECKLIST)
    assert refused.status_code == 403
    assert error_code(refused) == "KYC_DECIDE_NOT_ALLOWED"
    # edit_any staff still see the masked KYC status and details.
    kyc = api.get(f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.staff_b))
    assert kyc.status_code == 200
    assert kyc.json()["can_decide"] is False
    assert kyc.json()["can_view_documents"] is False

    api.post(
        f"{API}/drivers/{driver['id']}/manager",
        json={"staff_id": team.staff_b_id, "reason": "Test"},
        headers=bearer(team.owner.token),
    )
    old = decide(api, team.staff_a, identity, checklist=IDENTITY_CHECKLIST)
    assert old.status_code == 404  # the old manager no longer sees this driver's KYC
    assert decide(api, team.staff_b, identity, checklist=IDENTITY_CHECKLIST).status_code == 200
    assert decide(api, team.owner.token, licence, checklist=LICENCE_CHECKLIST).status_code == 200


def test_kyc_capture_is_for_owner_and_current_manager(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")
    _grant_edit_any(api, team)

    checks = [
        start_attempt(api, team.staff_b, driver["id"], "licence"),
        save_identity(api, team.staff_b, attempt),
        upload(api, team.staff_b, attempt, "id_front"),
        submit(api, team.staff_b, attempt),
        api.post(
            f"{API}/drivers/{driver['id']}/consents",
            json={"purpose": "kyc", "notice_version": "v1", "method": "in_person_checkbox"},
            headers=bearer(team.staff_b),
        ),
    ]
    for response in checks:
        assert response.status_code == 403, response.text
        assert error_code(response) == "DRIVER_NOT_EDITABLE"
    kyc = api.get(f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.staff_b)).json()
    assert kyc["can_capture"] is False
    assert (
        api.get(f"{API}/drivers/{driver['id']}/kyc", headers=bearer(team.staff_a)).json()[
            "can_capture"
        ]
        is True
    )


def test_the_registering_staff_member_can_finish_the_wizard(api: TestClient, team: Team) -> None:
    """The creator is the manager from the start, so registration works end to end."""
    driver = create_driver(api, team.staff_a)
    assert driver["managed_by"]["id"] == team.staff_a_id
    assert driver["can_reveal"] is True
    from tests.api.driver_helpers import jpeg_bytes

    photo = api.post(
        f"{API}/drivers/{driver['id']}/photo",
        files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")},
        headers=bearer(team.staff_a),
    )
    assert photo.status_code == 200
    record_consent(api, team.staff_a, driver["id"])
    identity = submitted_identity(api, team.staff_a, driver["id"])
    licence = submitted_licence(api, team.staff_a, driver["id"])
    assert decide(api, team.staff_a, identity, checklist=IDENTITY_CHECKLIST).status_code == 200
    assert decide(api, team.staff_a, licence, checklist=LICENCE_CHECKLIST).status_code == 200
    eligibility = api.get(f"{API}/drivers/{driver['id']}/eligibility", headers=bearer(team.staff_a))
    assert eligibility.json()["ok"] is True


def test_staff_kyc_queue_shows_only_drivers_they_manage_even_with_edit_any(
    api: TestClient, team: Team
) -> None:
    mine = create_driver(api, team.staff_b, 1)
    create_driver(api, team.staff_a, 2)
    _grant_edit_any(api, team)
    response = api.get(f"{API}/kyc/queue?bucket=pending", headers=bearer(team.staff_b))
    assert {row["driver"]["id"] for row in response.json()["items"]} == {mine["id"]}
    owner = api.get(f"{API}/kyc/queue?bucket=pending", headers=bearer(team.owner.token))
    assert len({row["driver"]["id"] for row in owner.json()["items"]}) == 2


# --- Storage (N15) --------------------------------------------------------------------------------


def test_the_database_row_holds_ciphertext(api: TestClient, team: Team, app_engine: Engine) -> None:
    case = _full_driver(api, team)
    with app_engine.connect() as connection:
        driver_row = connection.execute(
            text("SELECT address, date_of_birth FROM drivers WHERE id = :id"),
            {"id": case["driver"]["id"]},
        ).one()
        licence_row = connection.execute(
            text(
                "SELECT licence_number, date_of_birth FROM licence_details WHERE kyc_check_id = :id"
            ),
            {"id": case["licence"]},
        ).one()
    for value in (*driver_row, *licence_row):
        assert value and not _leaks(value)
        assert ":" in value  # key id prefix of the field cipher


def test_reopen_keeps_the_encrypted_licence_date_of_birth_readable(
    api: TestClient, team: Team
) -> None:
    case = _full_driver(api, team)
    approved = decide(api, team.owner.token, case["licence"], checklist=LICENCE_CHECKLIST)
    assert approved.status_code == 200
    reopened = api.post(
        f"{API}/kyc/attempts/{case['licence']}/reopen",
        json={"reason": "Test reopen"},
        headers=bearer(team.owner.token),
    )
    assert reopened.status_code == 201
    response = _reveal(api, team.owner.token, case["driver"]["id"], "licence_date_of_birth")
    assert response.json()["value"] == LICENCE_DOB


# --- Never in audit, history, timeline or logs (addition A) ---------------------------------------


def test_masked_values_never_reach_audit_history_timeline_or_logs(
    api: TestClient, team: Team, app_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        case = _full_driver(api, team)
        driver_id = case["driver"]["id"]
        url = f"{API}/drivers/{driver_id}"
        responses: list[Response] = [
            api.patch(
                url,
                json={"address": NEW_ADDRESS, "date_of_birth": NEW_DOB},
                headers=bearer(team.staff_a),
            ),
            decide(api, team.staff_a, case["identity"], "reject", reason="Test reject"),
            decide(api, team.staff_a, case["licence"], checklist=LICENCE_CHECKLIST),
            api.post(
                f"{API}/kyc/attempts/{case['licence']}/reopen",
                json={"reason": "Test reopen"},
                headers=bearer(team.owner.token),
            ),
            _reveal(api, team.staff_b, driver_id, "address"),  # refused
        ]
        for field in (
            "address",
            "date_of_birth",
            "licence_number",
            "licence_date_of_birth",
            "id_dob_or_yob",
            "id_gender",
        ):
            assert _reveal(api, team.owner.token, driver_id, field).status_code == 200
        for token in (team.owner.token, team.staff_a, team.staff_b):
            responses += [
                api.get(url, headers=bearer(token)),
                api.get(f"{url}/timeline", headers=bearer(token)),
                api.get(f"{url}/kyc", headers=bearer(token)),
                api.get(f"{API}/drivers", headers=bearer(token)),
                api.get(f"{API}/kyc/queue?bucket=under_review", headers=bearer(token)),
            ]
        responses.append(
            api.get(
                f"{API}/audit-logs?entity_type=driver&entity_id={driver_id}",
                headers=bearer(team.owner.token),
            )
        )
        responses.append(api.get(f"{API}/audit-logs", headers=bearer(team.owner.token)))

    for response in responses:
        assert not _leaks(response.text), (response.request.url, _leaks(response.text))

    with app_engine.connect() as connection:
        audit_rows = connection.execute(
            text(
                "SELECT action, coalesce(before::text, ''), coalesce(after::text, ''), "
                "coalesce(reason, '') FROM audit_logs"
            )
        ).all()
        event_rows = connection.execute(
            text("SELECT coalesce(reason, ''), from_status, to_status FROM kyc_events")
        ).all()
        history_rows = connection.execute(
            text("SELECT coalesce(reason, '') FROM driver_manager_history")
        ).all()
    assert audit_rows and event_rows
    for row in [*audit_rows, *event_rows, *history_rows]:
        joined = " ".join(str(v) for v in row)
        assert not _leaks(joined), (row[0], _leaks(joined))

    formatter = JsonFormatter()
    for record in caplog.records:
        line = formatter.format(record)
        assert not _leaks(line), line


def test_rate_limited_refusals_never_log_values(
    api: TestClient, team: Team, caplog: pytest.LogCaptureFixture
) -> None:
    api.post(f"{API}/settings", json={"reveal_limit_per_hour": 1}, headers=bearer(team.owner.token))
    driver = create_driver(api, team.staff_a, address=ADDRESS)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        _reveal(api, team.staff_a, driver["id"], "address")
        limited = _reveal(api, team.staff_a, driver["id"], "address")
    assert limited.status_code == 429
    formatter = JsonFormatter()
    for record in caplog.records:
        assert not _leaks(formatter.format(record))
