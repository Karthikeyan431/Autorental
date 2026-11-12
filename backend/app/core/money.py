"""Money is integer paise everywhere (hard constraint 4).

Rupee amounts enter the system only as `str` or `Decimal`; floats are refused because they
cannot represent paise exactly. Formatting to rupees is for display only.
"""

import re
from decimal import Decimal, InvalidOperation

_RUPEE_STRING = re.compile(r"^-?\d+(\.\d{1,2})?$")
_PAISE_PER_RUPEE = 100


class MoneyError(ValueError):
    """A value cannot be used as money."""


def to_paise(value: Decimal | str) -> int:
    """Convert a rupee amount ("300.00" or Decimal("300")) to integer paise (30000)."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
        raise MoneyError(f"Money must be a str or Decimal of rupees, not {type(value).__name__}.")

    if isinstance(value, str):
        text = value.strip()
        if not _RUPEE_STRING.fullmatch(text):
            raise MoneyError("Money text must look like 300 or 300.50 (at most 2 decimals).")
        amount = Decimal(text)
    else:
        amount = value
        if not amount.is_finite():
            raise MoneyError("Money must be a finite number.")

    try:
        paise = amount * _PAISE_PER_RUPEE
        if paise != paise.to_integral_value():
            raise MoneyError("Money cannot have more than 2 decimal places.")
        return int(paise)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise MoneyError("Money could not be converted.") from exc


def _group_indian(rupees: int) -> str:
    """1200000 -> '12,00,000' (last 3 digits, then groups of 2)."""
    digits = str(rupees)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def format_rupees(paise: int) -> str:
    """Format paise for display: 12000050 -> '₹1,20,000.50', 12000000 -> '₹1,20,000'.

    Whole amounts show no decimals; paise are shown only when non-zero.
    """
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise MoneyError(f"Paise must be an int, not {type(paise).__name__}.")
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), _PAISE_PER_RUPEE)
    text = f"{sign}₹{_group_indian(rupees)}"
    if rest:
        text += f".{rest:02d}"
    return text
