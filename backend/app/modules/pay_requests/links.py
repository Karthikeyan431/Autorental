"""UPI links, WhatsApp click-to-chat URLs, reference codes and QR codes
(docs/rent-and-payments.md §2). Pure functions; money stays integer paise (no floats).

* UPI: `upi://pay?pa=..&pn=..&am=300.00&cu=INR&tn=R00421112`. Each value is percent-encoded
  (spaces as %20, never "+", which some UPI apps show literally).
* WhatsApp: `https://wa.me/91XXXXXXXXXX?text=...`. Staff open it on their own phone and press
  Send; nothing is sent by the server (no paid API, rule 17).
* The QR encodes the same UPI link (Python `qrcode`, PNG through Pillow).
"""

import io
import re
from datetime import date
from urllib.parse import quote

import qrcode

from app.core.money import format_rupees

_PAISE_PER_RUPEE = 100
_TEMPLATE_KEYS = ("name", "amount", "upi_link", "reference_code", "business_name")
_PLACEHOLDER = re.compile(r"(?<!\{)\{(" + "|".join(_TEMPLATE_KEYS) + r")\}(?!\})")


def paise_to_upi_amount(paise: int) -> str:
    """30000 -> "300.00". Integer arithmetic only."""
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("A UPI amount must be integer paise.")
    if paise <= 0:
        raise ValueError("A UPI amount must be above 0.")
    rupees, rest = divmod(paise, _PAISE_PER_RUPEE)
    return f"{rupees}.{rest:02d}"


def _encode(value: str) -> str:
    return quote(value, safe="")


def upi_link(*, upi_id: str, payee_name: str | None, amount_paise: int, reference_code: str) -> str:
    parts = [f"pa={quote(upi_id, safe='@.')}"]
    if payee_name:
        parts.append(f"pn={_encode(payee_name)}")
    parts += [
        f"am={paise_to_upi_amount(amount_paise)}",
        "cu=INR",
        f"tn={_encode(reference_code)}",
    ]
    return "upi://pay?" + "&".join(parts)


def whatsapp_url(mobile: str, message: str) -> str:
    """`mobile` is stored as +91 and 10 digits; wa.me wants 91XXXXXXXXXX with no plus sign."""
    digits = re.sub(r"\D", "", mobile)[-10:]
    if len(digits) != 10:
        raise ValueError("A WhatsApp number needs 10 digits.")
    return f"https://wa.me/91{digits}?text={_encode(message)}"


def _rupees_text(paise: int) -> str:
    """For the message: the template already has the rupee sign, so "1,200" or "300.50"."""
    return format_rupees(paise).replace("₹", "")


def render_message(
    template: str,
    *,
    name: str,
    amount_paise: int,
    upi_link: str,
    reference_code: str,
    business_name: str,
) -> str:
    """Replace only the known placeholders; anything else in the template is left as it is
    (str.format would fail on stray braces typed by the owner)."""
    values = {
        "name": name,
        "amount": _rupees_text(amount_paise),
        "upi_link": upi_link,
        "reference_code": reference_code,
        "business_name": business_name,
    }
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def reference_code(driver_code: str, period_start: date) -> str:
    """`R` + the driver number (at least 4 digits) + MMDD of the period start: R00421112.
    Letters and digits only, because banks strip symbols from narrations."""
    digits = re.sub(r"\D", "", driver_code)
    if not digits:
        raise ValueError("A driver code needs a number.")
    return f"R{digits.zfill(4)}{period_start:%m%d}"


def qr_png(link: str) -> bytes:
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    code.add_data(link)
    code.make(fit=True)
    image = code.make_image()
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()
