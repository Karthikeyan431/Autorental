"""Rule 10: check_eligibility() as in docs/kyc.md. Each condition failing alone gives its reason."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.agreements.models import Agreement
from app.modules.drivers.models import Driver, DriverRestriction
from app.modules.kyc.eligibility import check_eligibility
from app.modules.kyc.models import KycCheck, LicenceDetails
from app.modules.users.models import User
from app.modules.vehicles.models import Vehicle
from tests.helpers import make_settings

TODAY = date(2026, 11, 13)


def _user(db: Session) -> User:
    user = User(
        name="Test Staff 301",
        mobile="+919000000301",
        password_hash="not-a-real-hash",
        role="staff",
    )
    db.add(user)
    db.flush()
    return user


def _check(
    db: Session, driver: Driver, check_type: str, status: str, *, simulated: bool = False
) -> KycCheck:
    check = KycCheck(
        driver_id=driver.id,
        check_type=check_type,
        attempt_no=1,
        method="manual",
        status=status,
        is_simulated=simulated,
        is_current=True,
    )
    db.add(check)
    db.flush()
    return check


def _licence(
    db: Session,
    check: KycCheck,
    *,
    non_transport: date | None,
    transport: date | None = None,
) -> None:
    db.add(
        LicenceDetails(
            kyc_check_id=check.id,
            driver_id=check.driver_id,
            licence_number="f1:not-a-real-ciphertext",
            licence_number_hash=f"test-hash-{check.id}",
            licence_number_last4="0001",
            name_on_licence="Test Driver 001",
            valid_until_non_transport=non_transport,
            valid_until_transport=transport,
            vehicle_classes=["3W-TEST"],
        )
    )
    db.flush()


Build = Callable[..., Driver]


@pytest.fixture
def eligible_driver(db: Session) -> Build:
    def build(
        *,
        identity: str = "approved",
        licence: str | None = "approved",
        valid_until: date | None = TODAY + timedelta(days=365),
        transport: date | None = None,
        status: str = "active",
        simulated: bool = False,
    ) -> Driver:
        staff = _user(db)
        driver = Driver(
            full_name="Test Driver 001",
            mobile="+919000000001",
            # Stored encrypted by the service (N15); this test never reads them.
            address="test:not-decrypted-here",
            date_of_birth="test:not-decrypted-here",
            account_status=status,
            created_by=staff.id,
            managed_by=staff.id,
        )
        db.add(driver)
        db.flush()
        _check(db, driver, "identity", identity, simulated=simulated)
        if licence is not None:
            check = _check(db, driver, "licence", licence)
            _licence(db, check, non_transport=valid_until, transport=transport)
        return driver

    return build


SETTINGS = make_settings()
PRODUCTION = make_settings(APP_ENV="production")


def _reasons(db: Session, driver: Driver, settings: Settings = SETTINGS) -> list[str]:
    result = check_eligibility(db, driver, TODAY, settings=settings)
    assert result.ok is (not result.reasons)
    return list(result.reasons)


def test_all_conditions_passing_is_ok(db: Session, eligible_driver: Build) -> None:
    assert _reasons(db, eligible_driver()) == []


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "rejected"])
def test_identity_not_approved(db: Session, eligible_driver: Build, status: str) -> None:
    assert _reasons(db, eligible_driver(identity=status)) == ["IDENTITY_NOT_APPROVED"]


@pytest.mark.parametrize(
    "status", ["draft", "submitted", "under_review", "rejected", "resubmission_required"]
)
def test_licence_not_approved(db: Session, eligible_driver: Build, status: str) -> None:
    assert _reasons(db, eligible_driver(licence=status)) == ["LICENCE_NOT_APPROVED"]


def test_no_licence_check_at_all(db: Session, eligible_driver: Build) -> None:
    assert _reasons(db, eligible_driver(licence=None)) == ["LICENCE_NOT_APPROVED"]


def test_licence_valid_until_yesterday_is_expired(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver(valid_until=TODAY - timedelta(days=1))
    assert _reasons(db, driver) == ["LICENCE_EXPIRED"]


def test_licence_valid_until_today_is_ok(db: Session, eligible_driver: Build) -> None:
    assert _reasons(db, eligible_driver(valid_until=TODAY)) == []


def test_expired_status_gives_licence_expired(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver(licence="expired", valid_until=TODAY - timedelta(days=3))
    assert _reasons(db, driver) == ["LICENCE_EXPIRED"]


def test_transport_validity_is_used_when_present(db: Session, eligible_driver: Build) -> None:
    # Q22 default: the transport date wins over the non-transport date.
    expired_transport = eligible_driver(
        valid_until=TODAY + timedelta(days=900), transport=TODAY - timedelta(days=1)
    )
    assert _reasons(db, expired_transport) == ["LICENCE_EXPIRED"]


def test_transport_validity_extends_an_older_non_transport_date(
    db: Session, eligible_driver: Build
) -> None:
    driver = eligible_driver(
        valid_until=TODAY - timedelta(days=10), transport=TODAY + timedelta(days=10)
    )
    assert _reasons(db, driver) == []


@pytest.mark.parametrize("status", ["suspended", "inactive"])
def test_account_not_active(db: Session, eligible_driver: Build, status: str) -> None:
    assert _reasons(db, eligible_driver(status=status)) == ["ACCOUNT_NOT_ACTIVE"]


def test_blocking_restriction(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver()
    db.add(
        DriverRestriction(
            driver_id=driver.id, reason="Test", is_blocking=True, placed_by=driver.created_by
        )
    )
    db.flush()
    assert _reasons(db, driver) == ["BLOCKING_RESTRICTION"]


def test_non_blocking_or_lifted_restrictions_do_not_block(
    db: Session, eligible_driver: Build
) -> None:
    from app.core.time import utc_now

    driver = eligible_driver()
    db.add_all(
        [
            DriverRestriction(
                driver_id=driver.id, reason="Test", is_blocking=False, placed_by=driver.created_by
            ),
            DriverRestriction(
                driver_id=driver.id,
                reason="Test",
                is_blocking=True,
                placed_by=driver.created_by,
                lifted_by=driver.created_by,
                lifted_at=utc_now(),
            ),
        ]
    )
    db.flush()
    assert _reasons(db, driver) == []


def test_simulated_checks_are_refused_in_production(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver(simulated=True)
    assert _reasons(db, driver, PRODUCTION) == ["SIMULATED_VERIFICATION"]
    assert _reasons(db, driver, SETTINGS) == []


def test_only_the_current_attempt_counts(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver()
    current = db.query(KycCheck).filter_by(driver_id=driver.id, check_type="identity").one()
    current.is_current = False
    db.flush()
    db.add(
        KycCheck(
            driver_id=driver.id,
            check_type="identity",
            attempt_no=2,
            method="manual",
            status="under_review",
            is_current=True,
        )
    )
    db.flush()
    assert _reasons(db, driver) == ["IDENTITY_NOT_APPROVED"]


def test_several_failures_are_all_reported_in_order(db: Session, eligible_driver: Build) -> None:
    driver = eligible_driver(identity="rejected", licence="draft", status="suspended")
    assert _reasons(db, driver) == [
        "IDENTITY_NOT_APPROVED",
        "LICENCE_NOT_APPROVED",
        "ACCOUNT_NOT_ACTIVE",
    ]


def test_an_active_agreement_gives_already_assigned(db: Session, eligible_driver: Build) -> None:
    """Week 5: has_active_agreement() reads the agreements table (rule 2)."""
    driver = eligible_driver()
    vehicle = Vehicle(registration_number="TT00EL0001", make="Demo", model="Test 3W")
    db.add(vehicle)
    db.flush()
    agreement = Agreement(
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        status="draft",
        start_date=TODAY,
        daily_rent_paise=30000,
        terms_version="test",
        created_by=driver.created_by,
    )
    db.add(agreement)
    db.flush()
    assert _reasons(db, driver) == []  # a draft does not count
    agreement.status = "active"
    agreement.activated_at = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)
    db.flush()
    assert _reasons(db, driver) == ["ALREADY_ASSIGNED"]
    agreement.status = "ended"
    agreement.end_date = TODAY
    agreement.ended_at = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    db.flush()
    assert _reasons(db, driver) == []
