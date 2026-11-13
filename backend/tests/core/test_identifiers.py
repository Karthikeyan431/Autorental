"""Licence numbers (normalised, keyed hash) and the full-Aadhaar guard (hard constraint 5)."""

import pytest
from pydantic import BaseModel, ValidationError

from app.core.identifiers import (
    LicenceHasher,
    NoAadhaarStr,
    contains_aadhaar_like,
    normalise_licence_number,
)
from tests.helpers import random_key_b64


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TEST-DL-0001", "TESTDL0001"),
        ("test dl 0001", "TESTDL0001"),
        ("  Test/DL.0001 ", "TESTDL0001"),
        ("TESTDL0001", "TESTDL0001"),
    ],
)
def test_licence_numbers_are_normalised(raw: str, expected: str) -> None:
    assert normalise_licence_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "AB1", "TEST DL 0001 !!", "X" * 30])
def test_bad_licence_numbers_are_refused(raw: str) -> None:
    with pytest.raises(ValueError) as caught:
        normalise_licence_number(raw)
    assert raw.strip() not in str(caught.value) or not raw.strip()


def test_the_hash_is_keyed_and_stable() -> None:
    key = random_key_b64()
    hasher = LicenceHasher(key)
    first = hasher.hash("TESTDL0001")
    assert first == LicenceHasher(key).hash("TESTDL0001")
    assert first != LicenceHasher(random_key_b64()).hash("TESTDL0001")
    assert first != hasher.hash("TESTDL0002")
    assert "TESTDL0001" not in first
    assert len(first) == 64


def test_the_hasher_needs_a_real_key() -> None:
    with pytest.raises(ValueError):
        LicenceHasher("")
    with pytest.raises(ValueError):
        LicenceHasher("short")


@pytest.mark.parametrize(
    "text",
    [
        "123412341234",
        "1234 1234 1234",
        "1234-1234-1234",
        "Name 1234 5678 9012 end",
        "id:123456789012.",
    ],
)
def test_aadhaar_like_numbers_are_detected(text: str) -> None:
    assert contains_aadhaar_like(text)


@pytest.mark.parametrize(
    "text",
    ["0001", "Test Driver 001", "1990-01-01", "9000000001", "+91 90000 00001", "1234 5678"],
)
def test_ordinary_text_passes(text: str) -> None:
    assert not contains_aadhaar_like(text)


class _Form(BaseModel):
    value: NoAadhaarStr


def test_the_validator_refuses_without_echoing_the_number() -> None:
    with pytest.raises(ValidationError) as caught:
        _Form(value="Test 1234 5678 9012")
    # The API error envelope returns only loc, msg and type (never the input), so the message
    # is what must not echo the number.
    (error,) = caught.value.errors()
    assert "1234" not in error["msg"]
    assert _Form(value="Test Driver 001").value == "Test Driver 001"
