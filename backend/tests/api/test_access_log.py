"""One access log line per API request: method, path, status, duration and request id only.

Never the body, the query string (it may hold search text) or the client's IP address.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from tests.api.conftest import Team
from tests.api.helpers import API, OWNER_MOBILE, bearer

SECRET_PASSWORD = "Never-logged-pass-0099"


def _access_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    formatter = JsonFormatter()
    return [json.loads(formatter.format(r)) for r in caplog.records if r.name == "arms.access"]


def test_one_line_per_request_with_the_expected_fields(
    api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="arms.access"):
        response = api.post(
            f"{API}/auth/login",
            json={"login": OWNER_MOBILE, "password": SECRET_PASSWORD},
            headers={"X-Request-ID": "0123456789abcdef0123456789abcdef"},
        )

    lines = _access_lines(caplog)
    assert len(lines) == 1
    line = lines[0]
    assert line["method"] == "POST"
    assert line["path"] == "/api/v1/auth/login"
    assert line["status"] == response.status_code == 401
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == "0123456789abcdef0123456789abcdef"
    text = json.dumps(line)
    assert SECRET_PASSWORD not in text
    assert "9000000001" not in text
    assert "127.0.0.1" not in text


def test_the_query_string_is_never_logged(
    api: TestClient, team: Team, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="arms.access"):
        response = api.get(
            f"{API}/drivers", params={"q": "Test Driver 042"}, headers=bearer(team.staff_a)
        )
    assert response.status_code == 200
    lines = _access_lines(caplog)
    assert [line["path"] for line in lines] == ["/api/v1/drivers"]
    assert "Test Driver 042" not in json.dumps(lines)
