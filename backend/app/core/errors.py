"""The API error envelope (docs/api.md) and stable error codes.

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

Business rules raise `AppError` with a stable code (usually 409). Unexpected errors become a
500 that says nothing about the cause; the log keeps the exception type and stack.
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
    """A refusal with a stable code, e.g. AppError("LICENCE_EXPIRED", "...", status_code=409)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


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


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # registered for this type only
        raise exc
    # Only where and why; never the submitted value, which may be personal data.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    code, message = _STATUS_CODES[422]
    return error_response(422, code, message, {"errors": errors})


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # registered for this type only
        raise exc
    code, message = _STATUS_CODES.get(exc.status_code, (f"HTTP_{exc.status_code}", "Error."))
    return error_response(exc.status_code, code, message)


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    _log.error("unhandled error", exc_info=(type(exc), exc, exc.__traceback__))
    return error_response(500, ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
