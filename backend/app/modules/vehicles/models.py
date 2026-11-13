"""Autos, their papers and maintenance (docs/data-model.md; Week 4).

* `registration_number` is stored normalised (upper case, no spaces or hyphens) and is unique.
* `status`: available / rented / maintenance / inactive. Only the agreements service (Week 5)
  sets `rented` and back; staff move between the other three.
* `vehicle_compliance` keeps every paper ever recorded; the latest `valid_until` of each kind is
  the current one. Insurance, fitness and permit raise expiry alerts (Q29).
* `maintenance_records.cost_paise` is integer paise (hard constraint 4).
"""

from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

VEHICLE_STATUSES = ("available", "rented", "maintenance", "inactive")
FUEL_TYPES = ("cng", "lpg", "petrol", "diesel", "electric")
PAPER_KINDS = ("insurance", "fitness", "permit", "pollution")
REGISTRATION_PATTERN = "^[A-Z0-9]{4,12}$"


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint(
            f"registration_number ~ '{REGISTRATION_PATTERN}'", name="registration_normalised"
        ),
        CheckConstraint(f"status IN ({_sql_list(VEHICLE_STATUSES)})", name="status_valid"),
        CheckConstraint(
            f"fuel_type IS NULL OR fuel_type IN ({_sql_list(FUEL_TYPES)})", name="fuel_type_valid"
        ),
        CheckConstraint("year IS NULL OR year BETWEEN 1980 AND 2100", name="year_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    registration_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    make: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    fuel_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="available")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class VehicleCompliance(TimestampMixin, Base):
    __tablename__ = "vehicle_compliance"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_sql_list(PAPER_KINDS)})", name="kind_valid"),
        CheckConstraint(
            "valid_from IS NULL OR valid_from <= valid_until", name="valid_from_before_until"
        ),
        Index("ix_vehicle_compliance_vehicle_kind", "vehicle_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vehicles.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id"))
    recorded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class MaintenanceRecord(TimestampMixin, Base):
    __tablename__ = "maintenance_records"
    __table_args__ = (
        CheckConstraint("ended_on IS NULL OR ended_on >= started_on", name="ended_after_started"),
        CheckConstraint("cost_paise IS NULL OR cost_paise >= 0", name="cost_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id"), nullable=False, index=True
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost_paise: Mapped[int | None] = mapped_column(BigInteger)
    recorded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
