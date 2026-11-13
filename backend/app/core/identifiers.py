"""Identity numbers: licence numbers and the full-Aadhaar guard (hard constraint 5).

* Licence numbers are normalised (upper case, letters and digits only), stored encrypted, and
  compared through a keyed HMAC-SHA256 so duplicates can be found without storing the number in
  a searchable form. A plain SHA-256 of a licence number could be brute-forced.
* `NoAadhaarStr` refuses any text containing a 12-digit run (with or without spaces or dashes),
  so a full Aadhaar number can never be typed into an identity or free-text field. The error
  never echoes the value.
"""

import base64
import binascii
import hashlib
import hmac
import re
from typing import Annotated

from pydantic import AfterValidator

_LICENCE_SEPARATORS = re.compile(r"[\s\-/.]")
_LICENCE_SHAPE = re.compile(r"[A-Z0-9]{6,20}")
_AADHAAR_LIKE = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_KEY_BYTES = 32


def normalise_licence_number(value: str) -> str:
    """Upper case with spaces, dashes, slashes and dots removed. Raises ValueError (without
    echoing the value) when the result is not 6-20 letters and digits."""
    cleaned = _LICENCE_SEPARATORS.sub("", value.strip()).upper()
    if not _LICENCE_SHAPE.fullmatch(cleaned):
        raise ValueError("Enter the licence number as printed (6 to 20 letters and digits).")
    return cleaned


class LicenceHasher:
    """Keyed hash of a normalised licence number, for the duplicate check."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("LOOKUP_HMAC_KEY must be base64.") from exc
        if len(key) != _KEY_BYTES:
            raise ValueError("LOOKUP_HMAC_KEY must be base64 of 32 bytes.")
        self._key = key

    def hash(self, normalised: str) -> str:
        return hmac.new(self._key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def contains_aadhaar_like(text: str) -> bool:
    """True if the text holds 12 digits in a row, optionally grouped 4-4-4 by spaces or dashes."""
    return _AADHAAR_LIKE.search(text) is not None


def _refuse_aadhaar_like(value: str) -> str:
    if contains_aadhaar_like(value):
        raise ValueError(
            "A full 12-digit number is not allowed here. Never record a full Aadhaar number."
        )
    return value


NoAadhaarStr = Annotated[str, AfterValidator(_refuse_aadhaar_like)]
