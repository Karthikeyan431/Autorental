"""Removal of personal data from logs and audit JSON (hard constraint 5).

Logs and audit `before`/`after` may hold ids, codes, statuses and amounts, never names,
mobiles, emails, addresses, dates of birth, Aadhaar or licence numbers, passwords or tokens.
"""

import re
from typing import Any

REDACTED = "[REDACTED]"
MASKED_NUMBER = "[REDACTED-NUMBER]"

# Exact keys that hold personal data.
_PERSONAL_KEYS = frozenset(
    {
        "name",
        "full_name",
        "name_on_document",
        "name_on_licence",
        "emergency_name",
        "mobile",
        "alt_mobile",
        "emergency_mobile",
        "phone",
        "email",
        "address",
        "date_of_birth",
        "dob",
        "dob_or_yob",
        "gender",
        # Masked identity fields under their reveal names (D45).
        "licence_date_of_birth",
        "id_dob_or_yob",
        "id_gender",
        "ip",
        "user_agent",
    }
)
# Any key containing one of these is sensitive.
_SENSITIVE_FRAGMENTS = (
    "aadhaar",
    "licence_number",
    "license_number",
    "password",
    "token",
    "secret",
    "totp",
    "otp",
    "recovery_code",
)

# Indian mobiles (optionally +91 / 91 prefixed) and Aadhaar-like 12-digit numbers.
_MOBILE = re.compile(r"(?<![\w])(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_TWELVE_DIGITS = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _PERSONAL_KEYS or any(f in lowered for f in _SENSITIVE_FRAGMENTS)


def redact(value: Any) -> Any:
    """Return a copy with sensitive keys replaced by REDACTED, recursively."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and is_sensitive_key(k) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def mask_text(text: str) -> str:
    """Mask mobile-like and Aadhaar-like numbers inside free text."""
    return _MOBILE.sub(MASKED_NUMBER, _TWELVE_DIGITS.sub(MASKED_NUMBER, text))
