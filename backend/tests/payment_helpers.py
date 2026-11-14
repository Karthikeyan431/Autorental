"""Builders for the Week 6 payment tests. Every value is obviously fake.

`world()` gives an owner, a managing staff member, another staff member, a daily driver with an
active ₹300 agreement from Monday 2 November 2026 and settings due at 10:00 with a test UPI ID.
Rows are flushed into the caller's session, never committed.
"""

import io
from dataclasses import dataclass
from datetime import date, datetime
from itertools import count

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.permissions import STAFF_DEFAULTS, CurrentUser, Permission
from app.modules.agreements.models import Agreement
from app.modules.drivers.models import Driver
from app.modules.payments.models import Payment
from app.modules.payments.schemas import AllocationItem, PaymentCreate
from app.modules.payments.service import record_payment
from app.modules.rent.accrual import accrue
from app.modules.rent.models import RentCharge
from app.modules.settings.models import SettingsVersion
from app.modules.users.models import User
from tests.rent_helpers import (
    ist,
    make_agreement,
    make_driver,
    make_settings_version,
    make_user,
    make_vehicle,
    rupees,
)

MON_2_NOV = date(2026, 11, 2)
THU_5_NOV = date(2026, 11, 5)
AT_SIX_THU = ist(THU_5_NOV, 18)
TEST_UPI_ID = "testautorentals@testbank"

_keys = count(1)


def png_proof() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 200, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def as_owner(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        role="owner",
        must_change_password=False,
        permissions=frozenset(p.value for p in Permission),
        family_id="test-family",
    )


def as_staff(user: User, *extra: Permission) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        role="staff",
        must_change_password=False,
        permissions=frozenset(p.value for p in (*STAFF_DEFAULTS, *extra)),
        family_id="test-family",
    )


@dataclass(frozen=True)
class World:
    owner: User
    manager: User
    other_staff: User
    driver: Driver
    agreement: Agreement
    settings: SettingsVersion


def world(
    db: Session,
    *,
    start: date = MON_2_NOV,
    now: datetime = AT_SIX_THU,
    rhythm: str = "daily",
    weekly_pay_day: int = 1,
    upi_id: str | None = TEST_UPI_ID,
    advance_adjustments_enabled: bool = True,
    refunds_enabled: bool = False,
) -> World:
    owner = make_user(db, role="owner")
    manager = make_user(db)
    other = make_user(db)
    settings = make_settings_version(
        db,
        weekly_pay_day=weekly_pay_day,
        upi_id=upi_id,
        advance_adjustments_enabled=advance_adjustments_enabled,
        refunds_enabled=refunds_enabled,
    )
    driver = make_driver(db, manager, rhythm=rhythm)
    agreement = make_agreement(db, driver, make_vehicle(db), manager, start=start, status="active")
    accrue(db, now=now)
    return World(owner, manager, other, driver, agreement, settings)


def another_driver(db: Session, w: World, *, start: date = MON_2_NOV) -> tuple[Driver, Agreement]:
    driver = make_driver(db, w.manager)
    agreement = make_agreement(
        db, driver, make_vehicle(db), w.manager, start=start, status="active"
    )
    return driver, agreement


def charges(db: Session, agreement_id: int) -> list[RentCharge]:
    return list(
        db.scalars(
            select(RentCharge)
            .where(RentCharge.agreement_id == agreement_id)
            .order_by(RentCharge.rent_date)
        )
    )


def record(
    db: Session,
    app_settings: Settings,
    user: CurrentUser,
    driver: Driver,
    amount: int,
    *,
    method: str = "cash",
    reference: str | None = None,
    purpose: str = "rent",
    received_on: date = THU_5_NOV,
    key: str | None = None,
    now: datetime = AT_SIX_THU,
) -> Payment:
    data = PaymentCreate(
        driver_id=driver.id,
        amount_paise=amount,
        method=method,  # type: ignore[arg-type]
        purpose=purpose,  # type: ignore[arg-type]
        reference=reference,
        received_on=received_on,
        idempotency_key=key or f"test-key-{next(_keys):06d}",
    )
    return record_payment(db, app_settings, user, data, proof=png_proof(), now=now)


def items(*pairs: tuple[RentCharge, int]) -> list[AllocationItem]:
    return [AllocationItem(rent_charge_id=c.id, amount_paise=a) for c, a in pairs]


__all__ = ["rupees"]
