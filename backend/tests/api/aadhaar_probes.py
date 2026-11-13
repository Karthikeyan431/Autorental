"""Realistic Aadhaar-like probes (hard constraints 5 and 7).

A real Aadhaar number has 12 digits and starts with 2-9. These probes are built at runtime from
a leading digit, so no realistic number ever appears as a literal in a test or fixture, and the
fixture scan (test_kyc_methods.py) stays strict for numbers starting with 2-9.
"""

from collections.abc import Callable


def realistic_number(first: int) -> str:
    """12 digits starting with `first` (2-9)."""
    if not 2 <= first <= 9:
        raise ValueError("A realistic probe starts with 2-9.")
    digits = [first] + [(first * 7 + i * 3) % 10 for i in range(1, 12)]
    return "".join(str(d) for d in digits)


def _plain(d: str) -> str:
    return d


def _spaced(d: str) -> str:
    return f"{d[:4]} {d[4:8]} {d[8:]}"


def _hyphenated(d: str) -> str:
    return f"{d[:4]}-{d[4:8]}-{d[8:]}"


FORMATS: tuple[Callable[[str], str], ...] = (_plain, _spaced, _hyphenated)

# One probe per leading digit 2-9, cycling through the three formats.
PROBES: tuple[str, ...] = tuple(
    FORMATS[i % len(FORMATS)](realistic_number(first)) for i, first in enumerate(range(2, 10))
)


def digits_of(probe: str) -> str:
    return "".join(ch for ch in probe if ch.isdigit())
