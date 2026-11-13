"""Vehicle paper expiry (Q29): alert `vehicle_alert_days` before and after expiry for insurance,
fitness and permit; idempotent; only the latest paper of each kind counts."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.vehicle_papers import run_vehicle_papers
from app.modules.alerts.models import Alert
from app.modules.vehicles.models import Vehicle, VehicleCompliance

TODAY = date(2026, 11, 13)


def _vehicle(db: Session, n: int, status: str = "available") -> Vehicle:
    vehicle = Vehicle(
        registration_number=f"XX00TT9{n:03d}", make="Demo", model="Test 3W", status=status
    )
    db.add(vehicle)
    db.flush()
    return vehicle


def _paper(db: Session, vehicle: Vehicle, kind: str, valid_until: date) -> VehicleCompliance:
    paper = VehicleCompliance(vehicle_id=vehicle.id, kind=kind, valid_until=valid_until)
    db.add(paper)
    db.flush()
    return paper


def _alerts(db: Session) -> list[tuple[str, int | None]]:
    return [(a.kind, a.entity_id) for a in db.scalars(select(Alert).order_by(Alert.id)).all()]


def test_alerts_within_the_window_and_after_expiry(db: Session) -> None:
    soon, gone, far = _vehicle(db, 1), _vehicle(db, 2), _vehicle(db, 3)
    _paper(db, soon, "insurance", TODAY + timedelta(days=30))
    _paper(db, gone, "fitness", TODAY - timedelta(days=1))
    _paper(db, far, "permit", TODAY + timedelta(days=31))
    result = run_vehicle_papers(db, TODAY, alert_days=30)
    assert result.alerts_created == 2
    assert _alerts(db) == [
        ("vehicle_paper_expiring", soon.id),
        ("vehicle_paper_expired", gone.id),
    ]


def test_running_again_creates_nothing_new(db: Session) -> None:
    _paper(db, _vehicle(db, 1), "insurance", TODAY + timedelta(days=3))
    run_vehicle_papers(db, TODAY, alert_days=30)
    assert run_vehicle_papers(db, TODAY, alert_days=30).alerts_created == 0
    assert run_vehicle_papers(db, TODAY + timedelta(days=1), alert_days=30).alerts_created == 0


def test_pollution_inactive_autos_and_renewed_papers_do_not_alert(db: Session) -> None:
    pollution = _vehicle(db, 1)
    _paper(db, pollution, "pollution", TODAY + timedelta(days=2))
    retired = _vehicle(db, 2, status="inactive")
    _paper(db, retired, "insurance", TODAY + timedelta(days=2))
    renewed = _vehicle(db, 3)
    _paper(db, renewed, "insurance", TODAY + timedelta(days=2))
    _paper(db, renewed, "insurance", TODAY + timedelta(days=367))
    assert run_vehicle_papers(db, TODAY, alert_days=30).alerts_created == 0


def test_alert_messages_name_the_auto_and_date_only(db: Session) -> None:
    vehicle = _vehicle(db, 1)
    _paper(db, vehicle, "permit", TODAY + timedelta(days=5))
    run_vehicle_papers(db, TODAY, alert_days=30)
    message = db.scalars(select(Alert.message)).one()
    assert message == "Auto XX00TT9001: permit valid until 2026-11-18."
