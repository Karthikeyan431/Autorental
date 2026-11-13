"""Vehicle paper expiry (Q29): alert `vehicle_alert_days` before expiry and after it, for the
current insurance, fitness and permit of every auto that is not inactive. No other automatic
action. Idempotent (dedupe keys); the caller owns the transaction. Saving a paper raises its
alert at once as well (app.modules.vehicles.service.add_paper)."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.modules.vehicles.service import raise_paper_alerts


@dataclass(frozen=True)
class VehiclePapersResult:
    alerts_created: int


def run_vehicle_papers(session: Session, today: date, *, alert_days: int) -> VehiclePapersResult:
    return VehiclePapersResult(
        alerts_created=raise_paper_alerts(session, today, alert_days=alert_days)
    )
