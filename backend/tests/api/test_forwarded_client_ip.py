"""The real client IP behind the Vite proxy (scripts\\dev.ps1 -Lan) or Caddy (production).

The proxy adds X-Forwarded-For. Uvicorn trusts it only from --forwarded-allow-ips, which
dev.ps1 sets to 127.0.0.1, and uses the address the trusted proxy saw. A request from anywhere
else keeps its own address, whatever header it sends. The login attempt log uses that address
(per-IP throttling), so the phone and the laptop no longer share one limit.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.modules.auth.models import LoginAttempt
from tests.api.helpers import API

ROOT = Path(__file__).resolve().parents[3]


def _client(app: FastAPI, peer: str) -> TestClient:
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")  # type: ignore[arg-type]
    return TestClient(
        wrapped,  # type: ignore[arg-type]
        base_url="https://testserver",
        raise_server_exceptions=False,
        client=(peer, 50000),
    )


def _failed_login(client: TestClient, forwarded_for: str) -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"login": "9000000999", "password": "Wrong-password-0000"},
        headers={"X-Forwarded-For": forwarded_for},
    )
    assert response.status_code == 401, response.text


def _last_attempt_ip(engine: Engine) -> str:
    with Session(engine) as session:
        ip = session.scalar(select(LoginAttempt.ip).order_by(LoginAttempt.id.desc()).limit(1))
    return str(ip)


def test_the_phones_address_is_used_when_the_local_proxy_forwards_it(
    app: FastAPI, app_engine: Engine
) -> None:
    _failed_login(_client(app, "127.0.0.1"), "192.168.1.50")
    assert _last_attempt_ip(app_engine) == "192.168.1.50"


def test_a_header_from_an_untrusted_peer_is_ignored(app: FastAPI, app_engine: Engine) -> None:
    _failed_login(_client(app, "192.168.1.9"), "10.9.9.9")
    assert _last_attempt_ip(app_engine) == "192.168.1.9"


def test_a_spoofed_first_hop_is_not_believed(app: FastAPI, app_engine: Engine) -> None:
    # The phone sends its own X-Forwarded-For; the proxy appends the address it really saw.
    _failed_login(_client(app, "127.0.0.1"), "10.9.9.9, 192.168.1.50")
    assert _last_attempt_ip(app_engine) == "192.168.1.50"


def test_dev_script_trusts_forwarded_headers_only_from_localhost() -> None:
    script = (ROOT / "scripts" / "dev.ps1").read_text(encoding="utf-8")
    assert "'--forwarded-allow-ips', '127.0.0.1'" in script
    vite = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "xfwd: lan" in vite
