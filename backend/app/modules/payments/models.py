"""Payments, allocations, advance transactions, reversal requests and receipt counters
(docs/data-model.md; docs/rent-and-payments.md §3, §5 to §7).

Created in migration 0007 because the day balance reads them (D50); Week 6 (migration 0008)
adds the approval, rejection, reversal and receipt columns.

An allocation counts toward a day's balance only when it is not reversed and its payment (or
advance transaction) is approved (rule 13).
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Identity, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

PAYMENT_STATUSES = ("awaiting_approval", "approved", "rejected", "reversed")
PAYMENT_METHODS = ("upi", "cash")
PAYMENT_SOURCES = ("pay_request", "upi_direct", "cash_office")
PAYMENT_PURPOSES = ("rent", "advance_deposit")
ADVANCE_KINDS = ("deposit", "adjustment", "refund", "reversal")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="payment_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drivers.id"), nullable=False)
    agreement_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agreements.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, server_default="rent")
    reference: Mapped[str | None] = mapped_column(Text)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    pay_request_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pay_requests.id"))
    statement_line_id: Mapped[int | None] = mapped_column(BigInteger)  # FK added in Week 7
    proof_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id"))
    recorded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="awaiting_approval")
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejected_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_no: Mapped[str | None] = mapped_column(Text, unique=True)
    receipt_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)


class AdvanceTransaction(TimestampMixin, Base):
    __tablename__ = "advance_transactions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    driver_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("drivers.id"), nullable=False)
    agreement_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agreements.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)  # signed
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class PaymentAllocation(TimestampMixin, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="alloc_positive"),
        CheckConstraint(
            "(payment_id IS NULL) <> (advance_transaction_id IS NULL)", name="one_source"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id"))
    advance_transaction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("advance_transactions.id")
    )
    rent_charge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rent_charges.id"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reversal_reason: Mapped[str | None] = mapped_column(Text)


class ReversalRequest(TimestampMixin, Base):
    """Q4: staff ask for a payment (or one allocation) to be reversed; the owner decides."""

    __tablename__ = "reversal_requests"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    payment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("payments.id"))
    allocation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payment_allocations.id")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    decision: Mapped[str | None] = mapped_column(Text)  # NULL = pending
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)


class ReceiptCounter(TimestampMixin, Base):
    """One row per financial year; row-locked while a number is issued, so there are no gaps."""

    __tablename__ = "receipt_counters"

    financial_year: Mapped[str] = mapped_column(Text, primary_key=True)
    last_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
