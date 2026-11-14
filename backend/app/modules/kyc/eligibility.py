"""Rule 10: the single eligibility check, exactly as in docs/kyc.md.

Agreement activation (app.modules.agreements.service) calls `check_eligibility()` inside its
transaction with row locks, on the start date and on today (D51). Reasons come back in a
fixed order so the UI and tests can rely on them.

Decision (Week 3 plan): a licence whose status is `expired` (set by the licence-expiry job)
reports LICENCE_EXPIRED rather than LICENCE_NOT_APPROVED.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.agreements.models import Agreement
from app.modules.drivers.models import Driver, DriverRestriction
from app.modules.kyc.models import KycCheck, LicenceDetails

IDENTITY_NOT_APPROVED = "IDENTITY_NOT_APPROVED"
LICENCE_NOT_APPROVED = "LICENCE_NOT_APPROVED"
LICENCE_EXPIRED = "LICENCE_EXPIRED"
ACCOUNT_NOT_ACTIVE = "ACCOUNT_NOT_ACTIVE"
BLOCKING_RESTRICTION = "BLOCKING_RESTRICTION"
ALREADY_ASSIGNED = "ALREADY_ASSIGNED"
SIMULATED_VERIFICATION = "SIMULATED_VERIFICATION"

REASON_MESSAGES = {
    IDENTITY_NOT_APPROVED: "Identity is not approved.",
    LICENCE_NOT_APPROVED: "Licence is not approved.",
    LICENCE_EXPIRED: "The licence is not valid on this date.",
    ACCOUNT_NOT_ACTIVE: "The driver's account is not active.",
    BLOCKING_RESTRICTION: "The owner has placed a blocking restriction.",
    ALREADY_ASSIGNED: "The driver already has an active auto.",
    SIMULATED_VERIFICATION: "A check used the demo verifier.",
}


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    licence_valid_until: date | None = None


def current_check(session: Session, driver_id: int, check_type: str) -> KycCheck | None:
    return session.scalars(
        select(KycCheck).where(
            KycCheck.driver_id == driver_id,
            KycCheck.check_type == check_type,
            KycCheck.is_current,
        )
    ).one_or_none()


def has_blocking_restriction(session: Session, driver_id: int) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    DriverRestriction.driver_id == driver_id,
                    DriverRestriction.is_blocking,
                    DriverRestriction.lifted_at.is_(None),
                )
            )
        )
    )


def has_active_agreement(session: Session, driver_id: int) -> bool:
    """Rule 2: the driver already has an auto. The database refuses a second active agreement
    too (partial unique index, migration 0007)."""
    return bool(
        session.scalar(
            select(exists().where(Agreement.driver_id == driver_id, Agreement.status == "active"))
        )
    )


def check_eligibility(
    session: Session, driver: Driver, on_date: date, *, settings: Settings
) -> Eligibility:
    reasons: list[str] = []
    identity = current_check(session, driver.id, "identity")
    licence = current_check(session, driver.id, "licence")
    valid_until: date | None = None
    if licence is not None:
        details = session.scalars(
            select(LicenceDetails).where(LicenceDetails.kyc_check_id == licence.id)
        ).one_or_none()
        valid_until = details.valid_until() if details is not None else None

    if identity is None or identity.status != "approved":
        reasons.append(IDENTITY_NOT_APPROVED)
    if licence is None or licence.status not in ("approved", "expired"):
        reasons.append(LICENCE_NOT_APPROVED)
    elif licence.status == "expired" or valid_until is None or valid_until < on_date:
        reasons.append(LICENCE_EXPIRED)
    if driver.account_status != "active":
        reasons.append(ACCOUNT_NOT_ACTIVE)
    if has_blocking_restriction(session, driver.id):
        reasons.append(BLOCKING_RESTRICTION)
    if has_active_agreement(session, driver.id):
        reasons.append(ALREADY_ASSIGNED)
    simulated = any(c is not None and c.is_simulated for c in (identity, licence))
    if settings.is_production and simulated:
        reasons.append(SIMULATED_VERIFICATION)
    return Eligibility(ok=not reasons, reasons=reasons, licence_valid_until=valid_until)
