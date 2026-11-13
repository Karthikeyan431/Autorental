"""Validation errors never echo the submitted value (hard constraint 5), in the response or logs.

A 12-digit Aadhaar-like number is sent to every identity field, as a string and as a number.
The raw response body and every captured log line (formatted exactly as the API window shows
them) must not contain it, and no error item carries pydantic's "input" or "ctx".
"""

import logging
from typing import Annotated, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.logging import JsonFormatter
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    create_driver,
    driver_payload,
    identity_details,
    new_attempt,
    record_consent,
)
from tests.api.helpers import API, bearer

AADHAAR_LIKE = "123412341234"
VARIANTS: list[Any] = [AADHAAR_LIKE, int(AADHAAR_LIKE), "1234 1234 1234"]
IDENTITY_FIELDS = ["document_type", "id_last4", "name_on_document", "dob_or_yob", "gender"]
DRIVER_FIELDS = [
    "full_name",
    "mobile",
    "alt_mobile",
    "address",
    "date_of_birth",
    "emergency_name",
    "emergency_mobile",
    "payment_rhythm",
]


def _digits_leaked(text: str) -> bool:
    return AADHAAR_LIKE in text or "1234 1234 1234" in text


def _assert_clean(response_text: str, caplog: pytest.LogCaptureFixture) -> None:
    assert not _digits_leaked(response_text), response_text
    formatter = JsonFormatter()
    for record in caplog.records:
        line = formatter.format(record)
        assert not _digits_leaked(line), line


def _assert_no_input_or_ctx(body: dict[str, Any]) -> None:
    for item in body["error"]["details"].get("errors", []):
        assert set(item) <= {"loc", "msg", "type"}, item


@pytest.mark.parametrize("value", VARIANTS, ids=["string", "number", "spaced"])
@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_identity_details_never_echo_the_number(
    api: TestClient,
    team: Team,
    caplog: pytest.LogCaptureFixture,
    field: str,
    value: Any,
) -> None:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    attempt = new_attempt(api, team.staff_a, driver["id"], "identity")

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = api.put(
            f"{API}/kyc/attempts/{attempt}/identity-details",
            json=identity_details(**{field: value}),
            headers=bearer(team.staff_a),
        )

    assert response.status_code == 422, response.text
    _assert_no_input_or_ctx(response.json())
    _assert_clean(response.text, caplog)


@pytest.mark.parametrize("value", VARIANTS, ids=["string", "number", "spaced"])
@pytest.mark.parametrize("field", DRIVER_FIELDS)
def test_driver_details_never_echo_the_number(
    api: TestClient,
    team: Team,
    caplog: pytest.LogCaptureFixture,
    field: str,
    value: Any,
) -> None:
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = api.post(
            f"{API}/drivers",
            json=driver_payload(**{field: value}),
            headers=bearer(team.staff_a),
        )

    assert response.status_code == 422, response.text
    _assert_no_input_or_ctx(response.json())
    _assert_clean(response.text, caplog)


class _Strict(BaseModel):
    last4: Annotated[str, Field(pattern=r"^[0-9]{4}$")]


class _Out(BaseModel):
    count: int


@pytest.fixture
def leaky_routes(app: FastAPI) -> TestClient:
    """Routes that hit pydantic errors outside FastAPI's request parsing (test app only)."""

    @app.get("/test-only/model-validate")
    def model_validate() -> dict[str, str]:
        _Strict.model_validate({"last4": AADHAAR_LIKE})
        return {}

    @app.get("/test-only/bad-response", response_model=_Out)
    def bad_response() -> dict[str, str]:
        return {"count": AADHAAR_LIKE + "x"}

    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)


def test_a_pydantic_error_inside_a_route_is_a_clean_422(
    leaky_routes: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = leaky_routes.get("/test-only/model-validate")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    _assert_no_input_or_ctx(response.json())
    _assert_clean(response.text, caplog)


def test_a_response_validation_error_is_logged_without_the_value(
    leaky_routes: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        response = leaky_routes.get("/test-only/bad-response")
    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    _assert_clean(response.text, caplog)
    assert any("validation" in r.getMessage().lower() for r in caplog.records)
