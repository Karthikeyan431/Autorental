"""Q23: alert 30 days before and on expiry; mark expired licences; no other automatic action."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.jobs.licence_expiry import run_licence_expiry
from app.modules.alerts.models import Alert
from app.modules.drivers.models import Driver
from app.modules.kyc.models import KycCheck, KycEvent, LicenceDetails
from app.modules.users.models import User

TODAY = date(2026, 11, 13)


def _driver_with_licence(
    db: Session, n: int, valid_until: date, status: str = "approved"
) -> KycCheck:
    staff = User(
        name=f"Test Staff {500 + n}",
        mobile=f"+9190000005{n:02d}",
        password_hash="not-a-real-hash",
        role="staff",
    )
    db.add(staff)
    db.flush()
    driver = Driver(
        full_name=f"Test Driver {n:03d}",
        mobile=f"+9190000{n:05d}",
        # Stored encrypted by the service (N15); this test never reads them.
        address="test:not-decrypted-here",
        date_of_birth="test:not-decrypted-here",
        created_by=staff.id,
        managed_by=staff.id,
    )
    db.add(driver)
    db.flush()
    check = KycCheck(
        driver_id=driver.id,
        check_type="licence",
        attempt_no=1,
        method="manual",
        status=status,
        is_current=True,
    )
    db.add(check)
    db.flush()
    db.add(
        LicenceDetails(
            kyc_check_id=check.id,
            driver_id=driver.id,
            licence_number="f1:not-real",
            licence_number_hash=f"test-hash-{n}",
            licence_number_last4="0001",
            name_on_licence=f"Test Driver {n:03d}",
            valid_until_non_transport=valid_until,
        )
    )
    db.flush()
    return check


def _alerts(db: Session) -> list[tuple[str, int | None]]:
    rows = db.scalars(select(Alert).order_by(Alert.id)).all()
    return [(a.kind, a.entity_id) for a in rows]


def test_alerts_within_the_window_and_marks_expired(db: Session) -> None:
    far = _driver_with_licence(db, 1, TODAY + timedelta(days=31))
    soon = _driver_with_licence(db, 2, TODAY + timedelta(days=30))
    today = _driver_with_licence(db, 3, TODAY)
    gone = _driver_with_licence(db, 4, TODAY - timedelta(days=1))

    result = run_licence_expiry(db, TODAY, alert_days=30)

    assert result.expired == 1
    assert sorted(_alerts(db)) == sorted(
        [
            ("licence_expiring", soon.driver_id),
            ("licence_expiring", today.driver_id),
            ("licence_expired", gone.driver_id),
        ]
    )
    db.refresh(gone)
    db.refresh(today)
    db.refresh(far)
    assert gone.status == "expired"
    assert today.status == "approved"  # valid until today is still valid
    assert far.status == "approved"
    event = db.scalars(select(KycEvent).where(KycEvent.kyc_check_id == gone.id)).one()
    assert (event.from_status, event.to_status, event.actor_id) == ("approved", "expired", None)
    assert db.scalar(
        select(AuditLog.id).where(AuditLog.action == "kyc.expired", AuditLog.entity_id == gone.id)
    )


def test_running_again_creates_nothing_new(db: Session) -> None:
    _driver_with_licence(db, 1, TODAY + timedelta(days=5))
    _driver_with_licence(db, 2, TODAY - timedelta(days=2))
    run_licence_expiry(db, TODAY, alert_days=30)
    before = _alerts(db)
    second = run_licence_expiry(db, TODAY, alert_days=30)
    third = run_licence_expiry(db, TODAY + timedelta(days=1), alert_days=30)
    assert second.expired == 0 and third.expired == 0
    assert second.alerts_created == 0 and third.alerts_created == 0
    assert _alerts(db) == before


def test_only_current_approved_licences_are_touched(db: Session) -> None:
    pending = _driver_with_licence(db, 1, TODAY - timedelta(days=5), status="under_review")
    old = _driver_with_licence(db, 2, TODAY - timedelta(days=5))
    old.is_current = False
    db.flush()
    result = run_licence_expiry(db, TODAY, alert_days=30)
    assert result.expired == 0
    assert _alerts(db) == []
    db.refresh(pending)
    assert pending.status == "under_review"


def test_alert_messages_carry_no_personal_data(db: Session) -> None:
    check = _driver_with_licence(db, 7, TODAY + timedelta(days=3))
    run_licence_expiry(db, TODAY, alert_days=30)
    alert = db.scalars(select(Alert)).one()
    driver = db.get(Driver, check.driver_id)
    assert driver is not None
    assert driver.code in alert.message
    assert "Test Driver" not in alert.message
    assert alert.severity == "warning"
