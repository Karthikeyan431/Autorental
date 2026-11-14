"""The printable agreement (reportlab) from a **placeholder template** (Q13: we write no legal
terms).

It holds the business details, the agreement number, the driver's name, code and mobile, the
auto, the rate and the dates, a box for the client's own terms, and signature lines. It never
holds a masked field (address, dates of birth, licence number; D45, D55). The built-in Helvetica
font has no rupee sign, so amounts are written "Rs. 1,20,000".
"""

import io
from dataclasses import dataclass
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.core.money import format_rupees

_LEFT = 20 * mm
_RIGHT = A4[0] - 20 * mm


@dataclass(frozen=True)
class AgreementSheet:
    business_name: str
    business_address: str | None
    agreement_no: str
    status: str
    driver_name: str
    driver_code: str
    driver_mobile: str
    registration_number: str
    make_model: str
    daily_rent_paise: int
    advance_required_paise: int
    start_date: date
    end_date: date | None
    terms_version: str
    printed_on: date


def _rupees(paise: int) -> str:
    return format_rupees(paise).replace("₹", "Rs. ")


def _day(value: date) -> str:
    return f"{value.day} {value:%B %Y}"


def render_agreement_pdf(sheet: AgreementSheet) -> bytes:
    buffer = io.BytesIO()
    # Uncompressed: one small page, and the text stays checkable (tests prove no masked field).
    canvas = Canvas(buffer, pagesize=A4, invariant=True, pageCompression=0)
    canvas.setTitle(f"Agreement {sheet.agreement_no}")
    canvas.setAuthor(sheet.business_name)
    y = A4[1] - 25 * mm

    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(_LEFT, y, sheet.business_name)
    y -= 6 * mm
    if sheet.business_address:
        canvas.setFont("Helvetica", 10)
        for line in sheet.business_address.splitlines()[:3]:
            canvas.drawString(_LEFT, y, line[:95])
            y -= 5 * mm
    y -= 6 * mm
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(_LEFT, y, "Auto-rickshaw rental agreement")
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(_RIGHT, y, f"No. {sheet.agreement_no}")
    if sheet.status == "draft":
        y -= 6 * mm
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(_LEFT, y, "DRAFT - not yet in force")
    y -= 12 * mm

    rows = [
        ("Driver", f"{sheet.driver_name} ({sheet.driver_code})"),
        ("Driver mobile", sheet.driver_mobile),
        ("Auto", f"{sheet.registration_number} - {sheet.make_model}"),
        ("Daily rent", f"{_rupees(sheet.daily_rent_paise)} per calendar day"),
        ("Advance (deposit)", _rupees(sheet.advance_required_paise)),
        ("Start date", _day(sheet.start_date)),
        ("Return date", _day(sheet.end_date) if sheet.end_date else "Not yet returned"),
    ]
    for label, value in rows:
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(_LEFT, y, label)
        canvas.setFont("Helvetica", 10)
        canvas.drawString(_LEFT + 45 * mm, y, value)
        y -= 7 * mm

    y -= 4 * mm
    canvas.setFont("Helvetica", 9)
    canvas.drawString(
        _LEFT, y, "Rent is charged for every calendar day, including Sundays and holidays."
    )
    y -= 10 * mm
    box_height = 70 * mm
    canvas.rect(_LEFT, y - box_height, _RIGHT - _LEFT, box_height)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(_LEFT + 4 * mm, y - 7 * mm, "Terms and conditions")
    canvas.setFont("Helvetica-Oblique", 9)
    canvas.drawString(
        _LEFT + 4 * mm,
        y - 14 * mm,
        f"Placeholder ({sheet.terms_version}): the business adds its own terms here.",
    )
    y -= box_height + 25 * mm

    canvas.setFont("Helvetica", 10)
    half = (_RIGHT - _LEFT) / 2
    for i, who in enumerate(("Driver's signature", f"For {sheet.business_name}")):
        x = _LEFT + i * half
        canvas.line(x, y, x + half - 10 * mm, y)
        canvas.drawString(x, y - 5 * mm, who[:45])
        canvas.drawString(x, y - 11 * mm, "Date:")

    canvas.setFont("Helvetica", 8)
    canvas.drawString(_LEFT, 15 * mm, f"Printed on {_day(sheet.printed_on)}")
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
