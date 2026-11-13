"""Load obviously fake demo data into the development database.

    python -m app.cli.seed

Seeds the first settings version and, when SEED_DEV_PASSWORD is set, a fake owner and 2 fake
staff (Week 2) who all use that password, and 5 fake drivers in different KYC states (Week 3).
Week 4 adds autos. Never runs when APP_ENV=production. Safe to run more than once.

Driver documents are images drawn here that say "DEMO - not a real document"; licence numbers
look like TEST-DL-0001 and identity last-4 digits are 0001 to 0005.

The seeded owner has no authenticator yet: TOTP is set up at the first browser sign-in.
"""

import io
import sys
from datetime import date, time, timedelta

from PIL import Image, ImageDraw
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.core.permissions import CurrentUser, effective_permissions
from app.core.security import check_password_policy
from app.core.time import business_date
from app.modules.drivers import service as drivers_service
from app.modules.drivers.models import Driver
from app.modules.drivers.schemas import DriverCreate
from app.modules.kyc import service as kyc_service
from app.modules.kyc.schemas import IdentityDetailsIn, LicenceDetailsIn
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import SettingsChanges
from app.modules.settings.service import create_settings_version
from app.modules.users.models import User
from app.modules.users.service import create_owner, create_staff, granted_codes, owner_exists

DEMO_SETTINGS = SettingsChanges(
    rent_due_time=time(10, 0),  # demo value from the worked example in rent-and-payments.md
    business_name="Test Auto Rentals (DEMO)",
    business_address="DEMO address, not a real place",
    business_upi_id="demo@upi",
    upi_payee_name="DEMO Payee",
)


DEMO_OWNER = {"name": "Test Owner (DEMO)", "mobile": "9000000001", "email": "owner@demo.test"}
DEMO_STAFF = (
    {"name": "Test Staff 001 (DEMO)", "mobile": "9000000002", "email": "staff001@demo.test"},
    {"name": "Test Staff 002 (DEMO)", "mobile": "9000000003", "email": None},
)


# (n, manager index into DEMO_STAFF, identity state, licence state, licence valid for N days)
DEMO_DRIVERS: tuple[tuple[int, int, str | None, str | None, int], ...] = (
    (1, 0, "approved", "approved", 3 * 365),
    (2, 0, "approved", "submitted", 2 * 365),
    (3, 1, "submitted", None, 0),
    (4, 1, None, None, 0),  # registered, no consent yet
    (5, 0, "approved", "approved", 20),  # licence expiring soon
)
DEMO_NOTICE_VERSION = "demo-notice-v1"
_TICKS = {
    check_type: {item.key: True for item in items}
    for check_type, items in kyc_service.CHECKLISTS.items()
}


class SeedRefusedError(RuntimeError):
    """The seed must never run against production, or with a weak dev password."""


def _seed_settings(session: Session) -> bool:
    if session.scalar(select(exists().where(SettingsVersion.id.is_not(None)))):
        return False
    create_settings_version(
        session, DEMO_SETTINGS, actor_id=None, reason="Development seed (fake data)"
    )
    return True


def _mobile_taken(session: Session, mobile: str) -> bool:
    return session.scalar(select(exists().where(User.mobile == f"+91{mobile}"))) is True


def _seed_users(session: Session, password: str) -> bool:
    try:
        check_password_policy(password)
    except AppError as exc:
        raise SeedRefusedError(f"SEED_DEV_PASSWORD is not acceptable: {exc.message}") from exc

    created = False
    if not owner_exists(session) and not _mobile_taken(session, DEMO_OWNER["mobile"] or ""):
        create_owner(
            session,
            name=DEMO_OWNER["name"] or "",
            mobile=DEMO_OWNER["mobile"] or "",
            email=DEMO_OWNER["email"],
            password=password,
        )
        created = True
    for staff in DEMO_STAFF:
        if _mobile_taken(session, staff["mobile"] or ""):
            continue
        create_staff(
            session,
            actor_id=None,
            name=staff["name"] or "",
            mobile=staff["mobile"] or "",
            email=staff["email"],
            password=password,
            must_change_password=False,
        )
        created = True
    return created


def _demo_image(label: str) -> bytes:
    image = Image.new("RGB", (480, 300), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 471, 291), outline=(200, 30, 30), width=4)
    draw.text((24, 40), "DEMO - not a real document", fill=(200, 30, 30))
    draw.text((24, 80), label, fill=(30, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _as_current_user(session: Session, user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        role=user.role,
        must_change_password=False,
        permissions=effective_permissions(user.role, granted_codes(session, user.id)),
        family_id="seed",
    )


def _seed_kyc_check(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    driver_id: int,
    *,
    n: int,
    check_type: str,
    state: str,
    valid_days: int,
) -> None:
    attempt = kyc_service.start_attempt(
        session, user, driver_id, check_type=check_type, method="manual", ip=None
    )
    if check_type == "identity":
        kyc_service.save_identity_details(
            session,
            user,
            attempt.id,
            IdentityDetailsIn(
                document_type="masked_aadhaar",
                id_last4=f"000{n}",
                name_on_document=f"Test Driver {n:03d} (DEMO)",
                dob_or_yob="1990",
            ),
            ip=None,
        )
        docs: tuple[str, ...] = ("id_front",)
    else:
        kyc_service.save_licence_details(
            session,
            settings,
            user,
            attempt.id,
            LicenceDetailsIn(
                licence_number=f"TEST-DL-000{n}",
                name_on_licence=f"Test Driver {n:03d} (DEMO)",
                date_of_birth=date(1990, 1, n),
                issue_date=date(2020, 1, 1),
                valid_until_non_transport=business_date() + timedelta(days=valid_days),
                vehicle_classes=["3W-DEMO"],
                issuing_authority="DEMO RTO",
            ),
            ip=None,
        )
        docs = ("licence_front", "licence_back")
    for doc_type in docs:
        kyc_service.upload_attempt_document(
            session,
            settings,
            user,
            attempt.id,
            doc_type=doc_type,
            data=_demo_image(f"{doc_type} {n:03d} - only the last 4 digits: 000{n}"),
            ip=None,
        )
    kyc_service.submit_attempt(session, user, attempt.id, ip=None)
    if state == "approved":
        kyc_service.decide_attempt(
            session,
            user,
            attempt.id,
            decision="approve",
            checklist=_TICKS[check_type],
            reason=None,
            ip=None,
        )


def _seed_drivers(session: Session, settings: Settings) -> bool:
    staff_rows = [
        session.scalars(select(User).where(User.mobile == f"+91{s['mobile']}")).one_or_none()
        for s in DEMO_STAFF
    ]
    staff = [_as_current_user(session, row) for row in staff_rows if row is not None]
    if len(staff) != len(DEMO_STAFF):
        return False  # the demo drivers need the demo staff (SEED_DEV_PASSWORD)
    if session.scalar(select(exists().where(Driver.mobile == "+919000010001"))):
        return False
    if not settings.LOOKUP_HMAC_KEY.get_secret_value():
        raise SeedRefusedError(
            "LOOKUP_HMAC_KEY is needed for the demo drivers. "
            "Run scripts\\db-setup.ps1 to add it to backend\\.env."
        )

    for n, manager, identity_state, licence_state, valid_days in DEMO_DRIVERS:
        user = staff[manager]
        driver = drivers_service.create_driver(
            session,
            user,
            DriverCreate(
                full_name=f"Test Driver {n:03d} (DEMO)",
                mobile=f"900001000{n}",
                address=f"DEMO address {n:03d}, Test Nagar",
                date_of_birth=date(1990, 1, n),
                emergency_name=f"Test Contact {n:03d} (DEMO)",
                emergency_mobile=f"900002000{n}",
            ),
            ip=None,
        )
        if identity_state is None:
            continue
        drivers_service.set_photo(
            session, settings, user, driver.id, _demo_image(f"Driver photo {n:03d}"), ip=None
        )
        kyc_service.record_consent(
            session,
            user,
            driver.id,
            purpose="kyc",
            notice_version=DEMO_NOTICE_VERSION,
            method="in_person_checkbox",
            ip=None,
        )
        for check_type, state in (("identity", identity_state), ("licence", licence_state)):
            if state is not None:
                _seed_kyc_check(
                    session,
                    settings,
                    user,
                    driver.id,
                    n=n,
                    check_type=check_type,
                    state=state,
                    valid_days=valid_days,
                )
    return True


def seed(session: Session, settings: Settings) -> bool:
    """Seed into the caller's transaction. Returns True if anything was inserted."""
    if settings.is_production:
        raise SeedRefusedError("The seed refuses to run when APP_ENV=production.")

    created = _seed_settings(session)
    password = settings.SEED_DEV_PASSWORD.get_secret_value()
    if password:
        try:
            created = _seed_users(session, password) or created
        except AppError as exc:  # e.g. the password contains a demo user's name
            raise SeedRefusedError(f"SEED_DEV_PASSWORD is not acceptable: {exc.message}") from exc
    return _seed_drivers(session, settings) or created


def main() -> int:
    settings = get_settings()
    if settings.is_production:
        print("Refusing to seed: APP_ENV=production.", file=sys.stderr)
        return 2
    engine = make_engine(settings.DATABASE_URL)
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            created = seed(session, settings)
    except SeedRefusedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(
        "Seeded the first settings version, demo users and demo drivers."
        if created
        else "Seed data already present."
    )
    if not settings.SEED_DEV_PASSWORD.get_secret_value():
        print("Demo users skipped: set SEED_DEV_PASSWORD in backend/.env to add them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
