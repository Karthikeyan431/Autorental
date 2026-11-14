"""Builders for the agreement and rent tests (Week 5). Every value is obviously fake.

Rows are added to the caller's session and flushed, never committed, so they work with the
rolled-back `db` fixture and with committing sessions alike.

`insert_approved_payment` writes a payment and its allocations directly (D50), for ledger tests
that are not about the payment flow. The Week 6 tests use the real services.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import count

from sqlalchemy.orm import Session

from app.core.time import BUSINESS_TZ
from app.modules.agreements.models import TERMS_VERSION, Agreement
from app.modules.drivers.models import Driver
from app.modules.kyc.models import KycCheck, LicenceDetails
from app.modules.payments.models import Payment, PaymentAllocation
from app.modules.rent.models import RentCharge
from app.modules.settings.models import DEFAULT_WHATSAPP_TEMPLATE, SettingsVersion
from app.modules.users.models import User
from app.modules.vehicles.models import Vehicle

_numbers = count(1)
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


def ist(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """A moment in Asia/Kolkata, as an aware datetime (converted to UTC by the database)."""
    return datetime.combine(day, time(hour, minute), tzinfo=BUSINESS_TZ)


def rupees(amount: int) -> int:
    """Whole rupees to paise, for readable test data."""
    return amount * 100


def make_user(db: Session, *, role: str = "staff") -> User:
    n = next(_numbers)
    user = User(
        name=f"Test Staff {500 + n:03d}" if role == "staff" else "Test Owner",
        mobile=f"+9190000{50000 + n:05d}",
        password_hash="not-a-real-hash",
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def make_settings_version(
    db: Session,
    *,
    due_time: time = time(10, 0),
    effective_from: datetime = LONG_AGO,
    weekly_pay_day: int = 1,
    due_day_offset: int = 0,
    max_backdate_days: int = 7,
    upi_id: str | None = None,
    advance_adjustments_enabled: bool = True,
    refunds_enabled: bool = False,
) -> SettingsVersion:
    version = SettingsVersion(
        effective_from=effective_from,
        rent_due_time=due_time,
        due_day_offset=due_day_offset,
        weekly_pay_day=weekly_pay_day,
        max_backdate_days=max_backdate_days,
        whatsapp_template=DEFAULT_WHATSAPP_TEMPLATE,
        business_name="Test Auto Rentals",
        business_upi_id=upi_id,
        upi_payee_name="Test Auto Rentals" if upi_id else None,
        advance_adjustments_enabled=advance_adjustments_enabled,
        refunds_enabled=refunds_enabled,
    )
    db.add(version)
    db.flush()
    return version


def make_driver(
    db: Session,
    manager: User,
    *,
    identity: str = "approved",
    licence: str | None = "approved",
    licence_valid_until: date | None = date(2030, 12, 31),
    account_status: str = "active",
    rhythm: str = "daily",
) -> Driver:
    n = next(_numbers)
    driver = Driver(
        full_name=f"Test Driver {n:03d}",
        mobile=f"+9190000{n:05d}",
        # Stored encrypted by the service (N15); these tests never read them.
        address="test:not-decrypted-here",
        date_of_birth="test:not-decrypted-here",
        account_status=account_status,
        payment_rhythm=rhythm,
        created_by=manager.id,
        managed_by=manager.id,
    )
    db.add(driver)
    db.flush()
    for check_type, status in (("identity", identity), ("licence", licence)):
        if status is None:
            continue
        check = KycCheck(
            driver_id=driver.id,
            check_type=check_type,
            attempt_no=1,
            method="manual",
            status=status,
            is_current=True,
        )
        db.add(check)
        db.flush()
        if check_type == "licence":
            db.add(
                LicenceDetails(
                    kyc_check_id=check.id,
                    driver_id=driver.id,
                    licence_number="f1:not-a-real-ciphertext",
                    licence_number_hash=f"test-hash-{check.id}",
                    licence_number_last4="0001",
                    name_on_licence=driver.full_name,
                    valid_until_non_transport=licence_valid_until,
                    vehicle_classes=["3W-TEST"],
                )
            )
            db.flush()
    return driver


def make_vehicle(db: Session, *, status: str = "available") -> Vehicle:
    n = next(_numbers)
    vehicle = Vehicle(
        registration_number=f"TT00AG{n:04d}", make="Demo", model="Test 3W", status=status
    )
    db.add(vehicle)
    db.flush()
    return vehicle


def make_agreement(
    db: Session,
    driver: Driver,
    vehicle: Vehicle,
    creator: User,
    *,
    start: date,
    rent: int = rupees(300),
    status: str = "draft",
    end: date | None = None,
) -> Agreement:
    """An agreement row written directly (no service): `active`/`ended` rows skip activation."""
    agreement = Agreement(
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        status=status,
        start_date=start,
        end_date=end,
        daily_rent_paise=rent,
        terms_version=TERMS_VERSION,
        created_by=creator.id,
    )
    if status in ("active", "ended"):
        agreement.activated_by = creator.id
        agreement.activated_at = ist(start, 9)
    if status == "ended":
        agreement.ended_by = creator.id
        agreement.ended_at = ist(end or start, 18)
    db.add(agreement)
    db.flush()
    return agreement


@dataclass(frozen=True)
class Scene:
    """A staff member, an eligible driver, an available auto and settings due at 10:00."""

    staff: User
    driver: Driver
    vehicle: Vehicle
    settings: SettingsVersion


def scene(db: Session, *, rhythm: str = "daily", weekly_pay_day: int = 1) -> Scene:
    staff = make_user(db)
    return Scene(
        staff=staff,
        driver=make_driver(db, staff, rhythm=rhythm),
        vehicle=make_vehicle(db),
        settings=make_settings_version(db, weekly_pay_day=weekly_pay_day),
    )


def insert_approved_payment(
    db: Session,
    driver: Driver,
    recorder: User,
    allocations: list[tuple[RentCharge, int]],
    *,
    method: str = "cash",
    status: str = "approved",
    received_on: date,
) -> Payment:
    """Week 5 test helper only: a payment with its confirmed days, inserted directly."""
    total = sum(amount for _, amount in allocations)
    payment = Payment(
        driver_id=driver.id,
        agreement_id=allocations[0][0].agreement_id if allocations else None,
        amount_paise=total,
        method=method,
        source="cash_office" if method == "cash" else "upi_direct",
        received_on=received_on,
        recorded_by=recorder.id,
        status=status,
    )
    if status == "approved":
        payment.approved_by = recorder.id
        payment.approved_at = ist(received_on, 12)
        # Week 6: an approved payment always has a receipt number (migration 0008).
        payment.receipt_no = f"RCPT/2026-27/{900000 + next(_numbers):06d}"
    if status == "rejected":
        # Week 6 (0008): a rejected payment records who rejected it, when and why.
        payment.rejected_by = recorder.id
        payment.rejected_at = ist(received_on, 12)
        payment.rejection_reason = "Test rejection"
    db.add(payment)
    db.flush()
    for charge, amount in allocations:
        db.add(
            PaymentAllocation(
                payment_id=payment.id,
                rent_charge_id=charge.id,
                amount_paise=amount,
                confirmed_by=recorder.id,
                confirmed_at=ist(received_on, 11),
            )
        )
    db.flush()
    return payment


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]
