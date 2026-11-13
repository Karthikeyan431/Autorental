"""Mobile normalisation (+91 and 10 digits)."""

import pytest

from app.core.phone import normalise_mobile


@pytest.mark.parametrize(
    "value",
    [
        "9000000101",
        "+919000000101",
        "+91 90000 00101",
        "919000000101",
        "09000000101",
        "90000-00101",
    ],
)
def test_accepted_formats(value: str) -> None:
    assert normalise_mobile(value) == "+919000000101"


@pytest.mark.parametrize("value", ["12345", "5000000101", "+1 9000000101", "90000001011", "abc"])
def test_refused_formats(value: str) -> None:
    with pytest.raises(ValueError) as error:
        normalise_mobile(value)
    assert value not in str(error.value)
