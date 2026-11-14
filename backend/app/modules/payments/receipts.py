"""Receipt numbers and the receipt PDF (docs/rent-and-payments.md §5; Q18: simple receipts).

Numbers are `RCPT/<financial year>/<serial>`, e.g. RCPT/2026-27/000123, issued at approval and
only then (rule 13). The financial year runs April to March in Asia/Kolkata. The serial comes
from the year's `receipt_counters` row, incremented with an upsert that row-locks it until the
approval commits; a rolled-back approval rolls the number back too, so there are no gaps.

The PDF holds the business details, the driver's name and code, the amount, method, reference,
the days covered and the receipt number; a reversed payment's receipt is marked CANCELLED. It
never holds a masked field (address, dates of birth, licence number; D45). The built-in Helvetica
font has no rupee sign, so amounts are written "Rs. 1,200".
"""

import io
from dataclasses import dataclass
from datetime import date

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.money import format_rupees

APRIL = 4
MAX_DAYS_LISTED = 40
_NEXT_SERIAL = text(
    "INSERT INTO receipt_counters (financial_year, last_number) VALUES (:fy, 1) "
    "ON CONFLICT (financial_year) DO UPDATE "
    "SET last_number = receipt_counters.last_number + 1, updated_at = now() "
    "RETURNING last_number"
)


def financial_year(day: date) -> str:
    start = day.year if day.month >= APRIL else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def next_receipt_no(session: Session, day: date) -> str:
    year = financial_year(day)
    serial = int(session.execute(_NEXT_SERIAL, {"fy": year}).scalar_one())
    return f"RCPT/{year}/{serial:06d}"


@dataclass(frozen=True)
class ReceiptDay:
    rent_date: date
    amount_paise: int


@dataclass(frozen=True)
class ReceiptSheet:
    business_name: str
    business_address: str | None
    receipt_no: str
    approved_on: date
    driver_name: str
    driver_code: str
    amount_paise: int
    method: str
    reference: str | None
    received_on: date
    purpose: str
    days: list[ReceiptDay]
    unallocated_paise: int
    cancelled: bool


def _rupees(paise: int) -> str:
    return format_rupees(paise).replace("₹", "Rs. ")


def _day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def render_receipt_pdf(sheet: ReceiptSheet) -> bytes:
    buffer = io.BytesIO()
    width, height = A5
    left, right = 12 * mm, width - 12 * mm
    # Uncompressed so the tests can check the text (no masked field).
    canvas = Canvas(buffer, pagesize=A5, invariant=True, pageCompression=0)
    canvas.setTitle(f"Receipt {sheet.receipt_no}")
    canvas.setAuthor(sheet.business_name)
    y = height - 18 * mm
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(left, y, sheet.business_name[:60])
    if sheet.business_address:
        canvas.setFont("Helvetica", 9)
        for line in sheet.business_address.splitlines()[:3]:
            y -= 4.5 * mm
            canvas.drawString(left, y, line[:80])
    y -= 10 * mm
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(left, y, "Payment receipt")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(right, y, sheet.receipt_no)
    if sheet.cancelled:
        y -= 7 * mm
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(left, y, "CANCELLED - this payment was reversed")
    y -= 10 * mm
    purpose = "Advance (deposit)" if sheet.purpose == "advance_deposit" else "Auto rent"
    rows = [
        ("Driver", f"{sheet.driver_name} ({sheet.driver_code})"),
        ("Amount", _rupees(sheet.amount_paise)),
        ("For", purpose),
        ("Method", "UPI" if sheet.method == "upi" else "Cash"),
        ("Reference", sheet.reference or "-"),
        ("Received on", _day(sheet.received_on)),
        ("Approved on", _day(sheet.approved_on)),
    ]
    for label, value in rows:
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(left, y, label)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(left + 30 * mm, y, value[:70])
        y -= 5.5 * mm
    if sheet.days:
        y -= 3 * mm
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(left, y, "Days covered")
        y -= 5.5 * mm
        canvas.setFont("Helvetica", 9)
        for item in sheet.days[:MAX_DAYS_LISTED]:
            canvas.drawString(left + 4 * mm, y, _day(item.rent_date))
            canvas.drawRightString(left + 70 * mm, y, _rupees(item.amount_paise))
            y -= 4.5 * mm
            if y < 25 * mm:
                canvas.showPage()
                canvas.setFont("Helvetica", 9)
                y = height - 18 * mm
        if len(sheet.days) > MAX_DAYS_LISTED:
            more = len(sheet.days) - MAX_DAYS_LISTED
            canvas.drawString(left + 4 * mm, y, f"... and {more} more days")
            y -= 4.5 * mm
    if sheet.unallocated_paise > 0:
        y -= 2 * mm
        canvas.drawString(
            left, y, f"Credit not yet applied to days: {_rupees(sheet.unallocated_paise)}"
        )
    canvas.setFont("Helvetica", 7)
    canvas.drawString(left, 12 * mm, "A simple receipt; not a tax invoice.")
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
