"""Indian mobile numbers, normalised to +91 followed by 10 digits."""

import re

_SEPARATORS = re.compile(r"[\s\-().]")
_TEN_DIGITS = re.compile(r"[6-9]\d{9}")


def normalise_mobile(value: str) -> str:
    """Accept 10 digits, or with a +91 / 91 / 0 prefix, with spaces or dashes. Raise ValueError
    (without echoing the value) for anything else."""
    digits = _SEPARATORS.sub("", value.strip())
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _TEN_DIGITS.fullmatch(digits):
        raise ValueError("Enter a 10-digit Indian mobile number.")
    return f"+91{digits}"


def looks_like_email(value: str) -> bool:
    return "@" in value
