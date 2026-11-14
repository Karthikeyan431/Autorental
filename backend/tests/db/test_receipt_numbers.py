"""Receipts: approving 50 payments at once gives 50 unique receipt numbers with no gaps
(docs/data-model.md receipt_counters)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.payments.approval import approve_payments
from app.modules.payments.models import Payment, ReceiptCounter
from tests.payment_helpers import AT_SIX_THU, as_owner, as_staff, record, world
from tests.rent_helpers import rupees


def test_fifty_approvals_give_fifty_gapless_receipt_numbers(
    db: Session, test_settings: Settings
) -> None:
    w = world(db)
    staff = as_staff(w.other_staff)
    ids = [record(db, test_settings, staff, w.driver, rupees(10)).id for _ in range(50)]
    results = approve_payments(db, as_owner(w.owner), ids, now=AT_SIX_THU)
    assert [r.outcome for r in results] == ["approved"] * 50
    numbers = list(db.scalars(select(Payment.receipt_no).where(Payment.id.in_(ids))))
    assert len(set(numbers)) == 50
    serials = sorted(int(n.rsplit("/", 1)[1]) for n in numbers if n is not None)
    assert serials == list(range(1, 51))
    assert all(n is not None and n.startswith("RCPT/2026-27/") for n in numbers)
    counter = db.get(ReceiptCounter, "2026-27")
    assert counter is not None and counter.last_number == 50


def test_a_refused_approval_uses_no_number(db: Session, test_settings: Settings) -> None:
    w = world(db)
    staff = as_staff(w.other_staff)
    owner = as_owner(w.owner)
    first = record(db, test_settings, staff, w.driver, rupees(10))
    approve_payments(db, owner, [first.id], now=AT_SIX_THU)
    again = approve_payments(db, owner, [first.id], now=AT_SIX_THU)  # already approved
    assert again[0].outcome == "refused"
    second = record(db, test_settings, staff, w.driver, rupees(10))
    (ok,) = approve_payments(db, owner, [second.id], now=AT_SIX_THU)
    assert ok.receipt_no == "RCPT/2026-27/000002"
