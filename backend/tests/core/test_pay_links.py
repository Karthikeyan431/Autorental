"""UPI links, WhatsApp URLs and reference codes (docs/rent-and-payments.md §2). No floats."""

from datetime import date
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app.modules.pay_requests import links
from app.modules.settings.models import DEFAULT_WHATSAPP_TEMPLATE


@pytest.mark.parametrize(
    ("paise", "text"),
    [(30000, "300.00"), (1, "0.01"), (5, "0.05"), (120000050, "1200000.50"), (99, "0.99")],
)
def test_upi_amount_has_two_decimals_from_paise(paise: int, text: str) -> None:
    assert links.paise_to_upi_amount(paise) == text


def test_upi_amount_refuses_floats_and_non_positive() -> None:
    with pytest.raises(TypeError):
        links.paise_to_upi_amount(300.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        links.paise_to_upi_amount(0)


def test_upi_link_url_encodes_the_payee_name_and_note() -> None:
    link = links.upi_link(
        upi_id="testautorentals@testbank",
        payee_name="Test Auto & Rentals",
        amount_paise=30000,
        reference_code="R00421112",
    )
    assert link.startswith("upi://pay?")
    assert "pn=Test%20Auto%20%26%20Rentals" in link
    query = parse_qs(urlsplit(link).query)
    assert query == {
        "pa": ["testautorentals@testbank"],
        "pn": ["Test Auto & Rentals"],
        "am": ["300.00"],
        "cu": ["INR"],
        "tn": ["R00421112"],
    }


def test_upi_link_without_a_payee_name_leaves_pn_out() -> None:
    link = links.upi_link(
        upi_id="testautorentals@testbank", payee_name=None, amount_paise=100, reference_code="R1"
    )
    assert "pn=" not in link
    assert "am=1.00" in link


def test_reference_code_is_r_driver_number_and_mmdd() -> None:
    assert links.reference_code("D0042", date(2026, 11, 12)) == "R00421112"
    assert links.reference_code("D0007", date(2027, 1, 3)) == "R00070103"
    assert links.reference_code("D12345", date(2026, 12, 31)) == "R123451231"
    assert links.reference_code("D0042", date(2026, 11, 12)).isalnum()


def test_whatsapp_url_uses_91_and_the_ten_digit_mobile() -> None:
    url = links.whatsapp_url("+919000012345", "Hello")
    assert url == "https://wa.me/919000012345?text=Hello"


def test_whatsapp_url_encodes_the_message() -> None:
    message = "Hello Test Driver 001, rent is ₹300. Pay here: upi://pay?pa=a@b&am=300.00 Ref R1"
    url = links.whatsapp_url("+919000012345", message)
    text = url.split("?text=", 1)[1]
    assert " " not in text and "&" not in text and "?" not in text
    assert unquote(text) == message


def test_the_default_template_renders_every_placeholder() -> None:
    message = links.render_message(
        DEFAULT_WHATSAPP_TEMPLATE,
        name="Test Driver 001",
        amount_paise=120000,
        upi_link="upi://pay?pa=x@y",
        reference_code="R00421112",
        business_name="Test Auto Rentals",
    )
    assert message == (
        "Hello Test Driver 001, today's auto rent is ₹1,200. Pay here: upi://pay?pa=x@y "
        "Ref R00421112. Thank you, Test Auto Rentals"
    )


def test_unknown_placeholders_and_braces_are_left_alone() -> None:
    message = links.render_message(
        "{name} {unknown} {{x}} {amount}",
        name="Test Driver 001",
        amount_paise=30050,
        upi_link="",
        reference_code="",
        business_name="",
    )
    assert message == "Test Driver 001 {unknown} {{x}} 300.50"


def test_qr_png_is_a_png() -> None:
    assert links.qr_png("upi://pay?pa=x@y&am=1.00").startswith(b"\x89PNG\r\n\x1a\n")
