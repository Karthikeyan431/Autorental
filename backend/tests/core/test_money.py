"""Money is integer paise; floats are refused (hard constraint 4)."""

from decimal import Decimal
from typing import Any

import pytest

from app.core.money import MoneyError, format_rupees, to_paise


def test_rupee_string_gives_paise() -> None:
    assert to_paise("300.00") == 30000


def test_result_is_a_plain_int() -> None:
    assert type(to_paise("300.00")) is int
    assert type(to_paise(Decimal("300"))) is int


def test_adding_paise_stays_int() -> None:
    total = to_paise("300.00") + to_paise("0.50")
    assert total == 30050
    assert type(total) is int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("300"), 30000),
        (Decimal("0.01"), 1),
        (Decimal("120000.50"), 12000050),
        ("120000.50", 12000050),
        ("0", 0),
        ("7", 700),
        ("2.5", 250),
        ("-300.5", -30050),
        (" 300.00 ", 30000),
    ],
)
def test_accepted_inputs(value: Decimal | str, expected: int) -> None:
    assert to_paise(value) == expected


@pytest.mark.parametrize("value", [300.0, 0.1, float("nan"), float("inf")])
def test_float_is_refused(value: float) -> None:
    with pytest.raises(MoneyError):
        to_paise(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [300, True, None, b"300"])
def test_other_types_are_refused(value: Any) -> None:
    with pytest.raises(MoneyError):
        to_paise(value)


@pytest.mark.parametrize(
    "value",
    ["300.001", "abc", "", "  ", "1e3", "300.", ".5", "1,200", "₹300", "--1", "+-1"],
)
def test_malformed_strings_are_refused(value: str) -> None:
    with pytest.raises(MoneyError):
        to_paise(value)


@pytest.mark.parametrize(
    "value", [Decimal("300.001"), Decimal("NaN"), Decimal("Infinity"), Decimal("sNaN")]
)
def test_bad_decimals_are_refused(value: Decimal) -> None:
    with pytest.raises(MoneyError):
        to_paise(value)


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (12000050, "₹1,20,000.50"),
        (12000000, "₹1,20,000"),
        (30000, "₹300"),
        (0, "₹0"),
        (1, "₹0.01"),
        (50, "₹0.50"),
        (99999, "₹999.99"),
        (100000, "₹1,000"),
        (10000000, "₹1,00,000"),
        (1000000000, "₹1,00,00,000"),
        (-30000, "-₹300"),
        (-12000050, "-₹1,20,000.50"),
    ],
)
def test_format_rupees_indian_grouping(paise: int, expected: str) -> None:
    assert format_rupees(paise) == expected


@pytest.mark.parametrize("value", [300.0, True, "300", Decimal("300")])
def test_format_refuses_non_int(value: Any) -> None:
    with pytest.raises(MoneyError):
        format_rupees(value)
