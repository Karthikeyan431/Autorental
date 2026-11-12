"""The error envelope from docs/api.md, and the request id."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import AppError, ErrorCode
from app.main import create_app
from tests.helpers import make_settings


def _app_with_test_routes() -> FastAPI:
    app = create_app(make_settings())

    @app.get("/api/v1/_test/refused")
    def refused() -> None:
        raise AppError(
            "LICENCE_EXPIRED",
            "The driver's licence expired on 2026-10-31.",
            status_code=409,
            details={"reasons": ["LICENCE_EXPIRED"]},
        )

    @app.get("/api/v1/_test/boom")
    def boom() -> None:
        raise RuntimeError("internal detail for Test Driver 001, mobile 9000012345")

    @app.get("/api/v1/_test/typed")
    def typed(page: int) -> dict[str, int]:
        return {"page": page}

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app_with_test_routes(), raise_server_exceptions=False) as test_client:
        yield test_client


def test_business_rule_refusal_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/_test/refused")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "LICENCE_EXPIRED"
    assert error["message"] == "The driver's licence expired on 2026-10-31."
    assert error["details"] == {"reasons": ["LICENCE_EXPIRED"]}
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_is_422_without_echoing_input(client: TestClient) -> None:
    response = client.get("/api/v1/_test/typed", params={"page": "not-a-number"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["errors"][0]["loc"] == ["query", "page"]
    assert "not-a-number" not in response.text


def test_unexpected_error_is_500_and_leaks_nothing(client: TestClient) -> None:
    response = client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "Test Driver" not in response.text
    assert "9000012345" not in response.text
    assert "RuntimeError" not in response.text


def test_unknown_route_is_404_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_is_405_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/_test/typed")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/v1/_test/typed", params={"page": 1})
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    int(request_id, 16)  # hex


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    incoming = "3f2b8c1e-aaaa-4bbb-8ccc-123456789abc"
    response = client.get(
        "/api/v1/_test/typed", params={"page": 1}, headers={"X-Request-ID": incoming}
    )
    assert response.headers["X-Request-ID"] == incoming


@pytest.mark.parametrize(
    "bad", ["has spaces in it", "x" * 200, "short", "<script>alert(1)</script>"]
)
def test_invalid_incoming_request_id_is_replaced(client: TestClient, bad: str) -> None:
    response = client.get("/api/v1/_test/typed", params={"page": 1}, headers={"X-Request-ID": bad})
    assert response.headers["X-Request-ID"] != bad
    assert len(response.headers["X-Request-ID"]) == 32


def test_error_codes_are_stable_strings() -> None:
    assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
    assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"
