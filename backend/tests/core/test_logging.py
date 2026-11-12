"""Structured logs never contain personal data (hard constraint 5)."""

import json
import logging
import sys

from app.core.logging import JsonFormatter
from app.core.redaction import REDACTED, mask_text, redact
from app.core.request_context import request_id_var


def test_personal_keys_are_redacted_recursively() -> None:
    data = {
        "full_name": "Test Driver 001",
        "mobile": "9000012345",
        "address": "1 Test Street",
        "date_of_birth": "1990-01-01",
        "user_id": 7,
        "nested": {"password": "x", "refresh_token": "y", "ok": 1},
        "items": [{"email": "test@example.invalid", "code": "D0001"}],
        "aadhaar_last4": "0000",
        "licence_number": "TEST0000",
        "totp_secret": "z",
    }
    result = redact(data)
    assert result["full_name"] == REDACTED
    assert result["mobile"] == REDACTED
    assert result["address"] == REDACTED
    assert result["date_of_birth"] == REDACTED
    assert result["nested"]["password"] == REDACTED
    assert result["nested"]["refresh_token"] == REDACTED
    assert result["items"][0]["email"] == REDACTED
    assert result["aadhaar_last4"] == REDACTED
    assert result["licence_number"] == REDACTED
    assert result["totp_secret"] == REDACTED
    # Non-personal values survive.
    assert result["user_id"] == 7
    assert result["nested"]["ok"] == 1
    assert result["items"][0]["code"] == "D0001"


def test_redact_does_not_modify_the_input() -> None:
    data = {"mobile": "9000012345"}
    redact(data)
    assert data == {"mobile": "9000012345"}


def test_mobile_and_aadhaar_like_numbers_are_masked_in_text() -> None:
    text = "call 9000012345 or +91 9000012346 or +91-9000012347; id 0000 1111 2222; id 000011112222"
    masked = mask_text(text)
    for leaked in ("9000012345", "9000012346", "9000012347", "0000 1111 2222", "000011112222"):
        assert leaked not in masked


def test_short_numbers_and_hex_ids_are_left_alone() -> None:
    text = "order 123 took 45 ms; request 3f2b8c1eaaaa4bbb8ccc123456789abc; year 2026"
    assert mask_text(text) == text


def _format(record: logging.LogRecord) -> dict[str, object]:
    output = JsonFormatter().format(record)
    assert "\n" not in output
    parsed: dict[str, object] = json.loads(output)
    return parsed


def test_json_formatter_includes_request_id_and_redacts_extras() -> None:
    token = request_id_var.set("abc123def456")
    try:
        record = logging.makeLogRecord(
            {
                "name": "arms.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "registered driver with mobile %s",
                "args": ("9000012345",),
                "full_name": "Test Driver 001",
                "driver_id": 42,
            }
        )
        payload = _format(record)
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "abc123def456"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "arms.test"
    assert "9000012345" not in str(payload["msg"])
    assert payload["full_name"] == REDACTED
    assert payload["driver_id"] == 42


def test_exceptions_are_logged_without_their_message() -> None:
    try:
        raise ValueError("Test Driver 001 lives at 1 Test Street")
    except ValueError:
        record = logging.makeLogRecord(
            {
                "name": "arms.test",
                "levelno": logging.ERROR,
                "levelname": "ERROR",
                "msg": "unhandled error",
                "exc_info": sys.exc_info(),
            }
        )
    payload = _format(record)
    assert payload["exc_type"] == "ValueError"
    assert "Test Driver" not in json.dumps(payload)
    assert "Test Street" not in json.dumps(payload)
    assert isinstance(payload["stack"], list)
