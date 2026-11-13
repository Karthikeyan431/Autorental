"""Licence expiry (Q23): alert the owner and the manager; no other automatic action.

For each driver's current, approved licence:
* valid until a date within `licence_alert_days` from today (today included): one
  `licence_expiring` alert;
* valid until a date before today: the check becomes `expired` (with an event and an audit
  entry) and one `licence_expired` alert is raised.

Idempotent: alerts carry a dedupe key, and only approved checks are moved to expired, so running
it again the same day (or the next) creates nothing new. The caller owns the transaction.
Per-user notifications for the owner and the manager arrive with the bell in Week 7; until then
the alerts show in the KYC queue's Expiring tab and on the dashboard.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.time import utc_now
from app.modules.alerts.models import Alert
from app.modules.drivers.models import Driver
from app.modules.kyc.models import KycCheck, KycEvent, LicenceDetails


@dataclass(frozen=True)
class LicenceExpiryResult:
    expired: int
    alerts_created: int


def _raise_alert(session: Session, *, kind: str, driver_id: int, key: str, message: str) -> bool:
    inserted = session.execute(
        insert(Alert)
        .values(
            kind=kind,
            entity_type="driver",
            entity_id=driver_id,
            severity="warning",
            message=message,
            dedupe_key=key,
        )
        .on_conflict_do_nothing(index_elements=[Alert.dedupe_key])
        .returning(Alert.id)
    ).scalar_one_or_none()
    return inserted is not None


def run_licence_expiry(session: Session, today: date, *, alert_days: int) -> LicenceExpiryResult:
    valid_until = func.coalesce(
        LicenceDetails.valid_until_transport, LicenceDetails.valid_until_non_transport
    )
    rows = session.execute(
        select(KycCheck, Driver.code, valid_until)
        .join(LicenceDetails, LicenceDetails.kyc_check_id == KycCheck.id)
        .join(Driver, Driver.id == KycCheck.driver_id)
        .where(
            KycCheck.check_type == "licence",
            KycCheck.is_current,
            KycCheck.status == "approved",
            valid_until.is_not(None),
            valid_until <= today + timedelta(days=alert_days),
        )
        .order_by(KycCheck.id)
        .with_for_update(of=KycCheck)
    ).all()

    expired = alerts = 0
    now = utc_now()
    for check, code, until in rows:
        if until < today:
            check.status = "expired"
            session.add(
                KycEvent(
                    kyc_check_id=check.id,
                    from_status="approved",
                    to_status="expired",
                    actor_id=None,
                    at=now,
                    reason=f"Licence valid until {until.isoformat()}",
                )
            )
            write_audit(
                session,
                action="kyc.expired",
                entity_type="kyc_check",
                entity_id=check.id,
                before={"status": "approved"},
                after={"status": "expired", "valid_until": until},
                reason="Licence expiry job",
            )
            expired += 1
            alerts += _raise_alert(
                session,
                kind="licence_expired",
                driver_id=check.driver_id,
                key=f"licence_expired:{check.id}:{until.isoformat()}",
                message=f"Driver {code}: the licence expired after {until.isoformat()}.",
            )
        else:
            alerts += _raise_alert(
                session,
                kind="licence_expiring",
                driver_id=check.driver_id,
                key=f"licence_expiring:{check.id}:{until.isoformat()}",
                message=f"Driver {code}: the licence is valid until {until.isoformat()}.",
            )
    session.flush()
    return LicenceExpiryResult(expired=expired, alerts_created=alerts)
