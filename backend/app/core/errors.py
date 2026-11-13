"""The API error envelope (docs/api.md) and stable error codes.

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

Business rules raise `AppError` with a stable code (usually 409). Unexpected errors become a
500 that says nothing about the cause; the log keeps the exception type and stack.
"""

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import REQUEST_ID_HEADER, get_request_id

_log = logging.getLogger("arms.errors")


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


_STATUS_CODES: dict[int, tuple[ErrorCode, str]] = {
    400: (ErrorCode.BAD_REQUEST, "The request could not be read."),
    401: (ErrorCode.UNAUTHENTICATED, "Please sign in."),
    403: (ErrorCode.FORBIDDEN, "You do not have permission to do this."),
    404: (ErrorCode.NOT_FOUND, "Not found."),
    405: (ErrorCode.METHOD_NOT_ALLOWED, "This action is not allowed here."),
    409: (ErrorCode.CONFLICT, "The action was refused."),
    422: (ErrorCode.VALIDATION_ERROR, "Some fields are not valid."),
    429: (ErrorCode.RATE_LIMITED, "Too many attempts. Please wait and try again."),
    503: (ErrorCode.SERVICE_UNAVAILABLE, "The service is unavailable. Please try again."),
}
_INTERNAL_MESSAGE = "Something went wrong. Please quote the request id if you report it."


class AppError(Exception):
    """A refusal with a stable code, e.g. AppError("LICENCE_EXPIRED", "...", status_code=409).

    Normally the request's transaction is rolled back. With `keep_changes=True` it is committed
    before the error is returned: used when the refusal itself must be recorded (a failed
    sign-in increments the lockout counter and writes its audit entry; a reused refresh token
    revokes its family).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
        keep_changes: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.keep_changes = keep_changes


def error_response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    request_id = get_request_id()
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def _app_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # registered for this type only
        raise exc
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


def safe_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Only where and why. Pydantic's "input" and "ctx" (and "url") are dropped everywhere:
    they carry the submitted value, which may be personal data (hard constraint 5)."""
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in errors
    ]


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's request parsing, or a model validated inside a route or service.
    if not isinstance(exc, (RequestValidationError, PydanticValidationError)):
        raise exc
    code, message = _STATUS_CODES[422]
    return error_response(422, code, message, {"errors": safe_errors(exc.errors())})


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered for this type only
        raise exc
    code, message = _STATUS_CODES.get(exc.status_code, (f"HTTP_{exc.status_code}", "Error."))
    return error_response(exc.status_code, code, message)


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ResponseValidationError):
        # Our own bug (a response that does not fit its model). Log where, never the value.
        _log.error(
            "response validation error",
            extra={
                "errors": [{"loc": e["loc"], "type": e["type"]} for e in safe_errors(exc.errors())]
            },
        )
        return error_response(500, ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE)
    _log.error("unhandled error", exc_info=(type(exc), exc, exc.__traceback__))
    return error_response(500, ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(PydanticValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
