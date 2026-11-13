"""Request id: accepted from a safe incoming X-Request-ID header or generated, returned on
every response, and attached to every log line and error envelope."""

import ipaddress
import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_access_log = logging.getLogger("arms.access")


def get_request_id() -> str | None:
    return request_id_var.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.fullmatch(candidate) else None
    return None


class RequestIdMiddleware:
    """Pure ASGI middleware. Logs one access line per request: method, path (never the query
    string, which may hold search text), status and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or new_request_id()
        request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:  # error responses may already carry it
                    headers.append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _access_log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    # On the record itself, so the line is right wherever it is formatted.
                    "request_id": request_id,
                },
            )


def client_ip(request: Request) -> str | None:
    """The caller's IP address, or None if it is not a valid address (e.g. the test client).

    In production uvicorn runs behind Caddy on the same host and trusts its X-Forwarded-For
    (uvicorn's default `forwarded_allow_ips` is 127.0.0.1), so this is the real client.
    """
    host = request.client.host if request.client else None
    if not host:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def user_agent(request: Request, limit: int = 300) -> str | None:
    value = request.headers.get("user-agent")
    return value[:limit] if value else None
