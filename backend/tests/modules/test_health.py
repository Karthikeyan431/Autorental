"""GET /api/v1/health reports API and database status."""

from fastapi.testclient import TestClient

from app.main import create_app
from app.version import __version__
from tests.helpers import make_settings


def test_health_is_200_with_the_database_up(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": __version__}
    assert response.headers["X-Request-ID"]


def test_health_is_503_when_the_database_is_down() -> None:
    app = create_app(make_settings())  # points at an unreachable database
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "unavailable", "version": __version__}


def test_health_needs_no_sign_in(client: TestClient) -> None:
    assert client.get("/api/v1/health", headers={}).status_code == 200
