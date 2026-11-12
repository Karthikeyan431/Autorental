"""Structured JSON logging. One JSON object per line, with the request id, and with personal
data removed: extra fields are redacted by key, the message is masked for mobile- and
Aadhaar-like numbers, and exceptions are logged by type and stack location only (their
message may contain personal data)."""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from app.core.redaction import mask_text, redact
from app.core.request_context import get_request_id

# Attributes every LogRecord has; anything else was passed with `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask_text(record.getMessage()),
            "request_id": get_request_id(),
        }
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        payload.update(redact(extras))

        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _exc, tb = record.exc_info
            payload["exc_type"] = exc_type.__name__
            payload["stack"] = [
                f"{frame.filename}:{frame.lineno} in {frame.name}"
                for frame in traceback.extract_tb(tb)
            ][-15:]
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Send all logs (ours and the libraries') to stderr as JSON lines."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    # Uvicorn's access log includes client IPs and query strings; we log requests ourselves.
    logging.getLogger("uvicorn.access").disabled = True
