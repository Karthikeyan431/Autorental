"""Agreements: draft, activate, end, cancel (rules 2, 6 and 10; Q1, Q2, Q10; D20; D51, D52).

* **Draft:** an available auto (VEHICLE_NOT_AVAILABLE), a start date at most
  `max_backdate_days` before today (START_DATE_TOO_EARLY, D51) and a fixed daily rate (Q10).
* **Activate**, in one transaction: refuse at once while no rent due time is set (D20); lock
  the agreement, then the driver, then the auto (always this order, so two activations never
  deadlock); run `check_eligibility()` on the start date **and** today (D51); check the auto is
  available and free on the start date (Q1); set the agreement active and the auto rented;
  write the audit entry. Every refusal lists all of its reasons (NOT_ELIGIBLE). The database
  constraints back rule 2 if anything slips through (AGREEMENT_OVERLAP).
* **End:** the return day is charged in full (Q2). It may be in the past but never before the
  start date or after today (END_DATE_NOT_ALLOWED). Charges already created after it are never
  deleted; each gets a pending waiver for the owner to decide, with the reason "Returned on
  <date>, recorded late" (D52). The auto is set available at once; the `[]` exclusion
  constraint and the eligibility check stop a new agreement starting on the return day (Q1).
* **Cancel:** drafts only.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import time as clock
from app.core.audit import write_audit
from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import Page, PageParams
from app.core.permissions import CurrentUser
from app.core.time import business_date
from app.modules.agreements.models import TERMS_VERSION, Agreement
from app.modules.agreements.pdf import AgreementSheet, render_agreement_pdf
from app.modules.agreements.schemas import (
    AgreementCancel,
    AgreementCreate,
    AgreementEnd,
    AgreementOut,
    DriverBrief,
    EligibilityOut,
    EligibilityReason,
    VehicleBrief,
)
from app.modules.documents.service import store_document
from app.modules.drivers.access import can_see_kyc, not_found
from app.modules.drivers.models import Driver
from app.modules.drivers.service import get_driver, user_refs
from app.modules.kyc.eligibility import REASON_MESSAGES, check_eligibility
from app.modules.rent.accrual import (
    RENT_DUE_TIME_MESSAGE,
    RENT_DUE_TIME_NOT_SET,
    require_rent_settings,
)
from app.modules.rent.adjustments import add_adjustment, late_return_reason, lock_agreement
from app.modules.rent.ledger import charge_figures
from app.modules.rent.models import ChargeAdjustment, RentCharge
from app.modules.settings.schemas import SettingsValues
from app.modules.settings.service import get_current_settings
from app.modules.vehicles.models import Vehicle
from app.modules.vehicles.service import get_vehicle, require_selectable_vehicle

VEHICLE_NOT_AVAILABLE = "VEHICLE_NOT_AVAILABLE"
VEHICLE_RETURNED_ON_START = "VEHICLE_RETURNED_ON_START"
VEHICLE_PERIOD_OVERLAP = "VEHICLE_PERIOD_OVERLAP"
DRIVER_PERIOD_OVERLAP = "DRIVER_PERIOD_OVERLAP"
START_DATE_TOO_EARLY = "START_DATE_TOO_EARLY"
START_DATE_IN_FUTURE = "START_DATE_IN_FUTURE"
KYC_NOT_COMPLETE = "KYC_NOT_COMPLETE"
# D33/D46: KYC status is for the owner, the current manager and `drivers.edit_any`. Anyone else
# who may manage agreements sees these reasons as one KYC_NOT_COMPLETE (D56).
KYC_REASONS = frozenset(
    {"IDENTITY_NOT_APPROVED", "LICENCE_NOT_APPROVED", "LICENCE_EXPIRED", "SIMULATED_VERIFICATION"}
)

ACTIVATION_MESSAGES = {
    **REASON_MESSAGES,
    VEHICLE_NOT_AVAILABLE: "The auto is not available (rented, in maintenance or inactive).",
    VEHICLE_RETURNED_ON_START: "The auto was returned on this date; it is available from the "
    "next day.",
    VEHICLE_PERIOD_OVERLAP: "The auto was rented during these dates.",
    DRIVER_PERIOD_OVERLAP: "The driver had another auto during these dates.",
    START_DATE_TOO_EARLY: "The start date is too far in the past.",
    START_DATE_IN_FUTURE: "The agreement can be activated from its start date.",
    RENT_DUE_TIME_NOT_SET: RENT_DUE_TIME_MESSAGE,
    KYC_NOT_COMPLETE: "KYC is not complete for this driver. Ask the driver's manager.",
}
# The order the reasons are listed in (eligibility first, as in docs/kyc.md).
_ORDER = [
    "IDENTITY_NOT_APPROVED",
    "LICENCE_NOT_APPROVED",
    "LICENCE_EXPIRED",
    "ACCOUNT_NOT_ACTIVE",
    "BLOCKING_RESTRICTION",
    "ALREADY_ASSIGNED",
    "SIMULATED_VERIFICATION",
    KYC_NOT_COMPLETE,
    DRIVER_PERIOD_OVERLAP,
    START_DATE_TOO_EARLY,
    START_DATE_IN_FUTURE,
    VEHICLE_NOT_AVAILABLE,
    VEHICLE_RETURNED_ON_START,
    VEHICLE_PERIOD_OVERLAP,
]


@dataclass(frozen=True)
class EndResult:
    agreement: Agreement
    waivers: list[ChargeAdjustment]
    vehicle_available_from: date


@dataclass
class Assessment:
    reasons: list[str] = field(default_factory=list)
    vehicle_available_from: date | None = None
    max_backdate_days: int = 7

    def details(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "reasons": self.reasons,
            "messages": {code: ACTIVATION_MESSAGES[code] for code in self.reasons},
        }
        if self.vehicle_available_from is not None:
            details["vehicle_available_from"] = self.vehicle_available_from.isoformat()
        if START_DATE_TOO_EARLY in self.reasons:
            details["max_backdate_days"] = self.max_backdate_days
        return details


def visible_reasons(user: CurrentUser, driver: Driver, reasons: list[str]) -> list[str]:
    """The reasons this user may see (D56): KYC reasons collapse to KYC_NOT_COMPLETE for staff
    who may not see this driver's KYC."""
    if can_see_kyc(user, driver):
        return reasons
    shown: list[str] = []
    for code in reasons:
        code = KYC_NOT_COMPLETE if code in KYC_REASONS else code
        if code not in shown:
            shown.append(code)
    return shown


def max_backdate_days(session: Session, now: datetime) -> int:
    current = get_current_settings(session, now)
    if current is not None:
        return current.max_backdate_days
    default = SettingsValues.model_fields["max_backdate_days"].default
    return int(default)


def _latest_end(
    session: Session, column: Any, value: int, start: date, exclude_id: int | None
) -> date | None:
    """The latest end date of an ended agreement on the same driver or auto that reaches the
    start date (the `[]` exclusion constraint would refuse the new one)."""
    query = select(func.max(Agreement.end_date)).where(
        column == value, Agreement.status == "ended", Agreement.end_date >= start
    )
    if exclude_id is not None:
        query = query.where(Agreement.id != exclude_id)
    result: date | None = session.scalar(query)
    return result


def assess(
    session: Session,
    driver: Driver,
    vehicle: Vehicle,
    start: date,
    *,
    settings: Settings,
    now: datetime,
    exclude_id: int | None = None,
) -> Assessment:
    """Every reason this driver cannot take this auto from `start`, in a fixed order."""
    today = business_date(now)
    found: set[str] = set()
    for on_date in {start, today}:
        found.update(check_eligibility(session, driver, on_date, settings=settings).reasons)
    result = Assessment(max_backdate_days=max_backdate_days(session, now))
    if start < today - timedelta(days=result.max_backdate_days):
        found.add(START_DATE_TOO_EARLY)
    if start > today:
        found.add(START_DATE_IN_FUTURE)
    if _latest_end(session, Agreement.driver_id, driver.id, start, exclude_id) is not None:
        found.add(DRIVER_PERIOD_OVERLAP)
    if vehicle.status != "available":
        found.add(VEHICLE_NOT_AVAILABLE)
    else:
        returned = _latest_end(session, Agreement.vehicle_id, vehicle.id, start, exclude_id)
        if returned is not None:
            found.add(VEHICLE_RETURNED_ON_START if returned == start else VEHICLE_PERIOD_OVERLAP)
            result.vehicle_available_from = returned + timedelta(days=1)
    result.reasons = [code for code in _ORDER if code in found]
    return result


# --- Draft ----------------------------------------------------------------------------------------


def create_draft(
    session: Session,
    user: CurrentUser,
    data: AgreementCreate,
    *,
    now: datetime | None = None,
    ip: str | None = None,
) -> Agreement:
    moment = now or clock.utc_now()
    today = business_date(moment)
    driver = get_driver(session, data.driver_id)
    vehicle = require_selectable_vehicle(session, data.vehicle_id)
    limit = max_backdate_days(session, moment)
    if data.start_date < today - timedelta(days=limit):
        raise AppError(
            START_DATE_TOO_EARLY,
            f"The start date can be at most {limit} days before today.",
            details={
                "max_backdate_days": limit,
                "earliest": (today - timedelta(days=limit)).isoformat(),
            },
        )
    agreement = Agreement(
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        status="draft",
        start_date=data.start_date,
        daily_rent_paise=data.daily_rent_paise,
        advance_required_paise=data.advance_required_paise,
        terms_version=TERMS_VERSION,
        created_by=user.id,
    )
    session.add(agreement)
    session.flush()
    session.refresh(agreement, ["agreement_no"])
    write_audit(
        session,
        action="agreement.created",
        entity_type="agreement",
        entity_id=agreement.id,
        actor_id=user.id,
        after={
            "agreement_no": agreement.agreement_no,
            "driver_id": driver.id,
            "vehicle_id": vehicle.id,
            "start_date": data.start_date,
            "daily_rent_paise": data.daily_rent_paise,
            "advance_required_paise": data.advance_required_paise,
        },
        ip=ip,
    )
    return agreement


def eligibility_preview(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    vehicle_id: int,
    start: date,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> EligibilityOut:
    """The live panel on the New agreement screen. No locks; activation checks again."""
    moment = now or clock.utc_now()
    driver = get_driver(session, driver_id)
    vehicle = get_vehicle(session, vehicle_id)
    result = assess(session, driver, vehicle, start, settings=settings, now=moment)
    reasons = visible_reasons(user, driver, result.reasons)
    if get_current_settings(session, moment) is None:
        reasons.append(RENT_DUE_TIME_NOT_SET)
    return EligibilityOut(
        ok=not reasons,
        reasons=[EligibilityReason(code=c, message=ACTIVATION_MESSAGES[c]) for c in reasons],
        vehicle_available_from=result.vehicle_available_from,
        max_backdate_days=result.max_backdate_days,
    )


# --- Activate -------------------------------------------------------------------------------------


def _invalid_transition(action: str, status: str) -> AppError:
    return AppError(
        "AGREEMENT_INVALID_TRANSITION",
        f"An agreement that is {status} cannot be {action}.",
        details={"status": status},
    )


def _lock_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    return get_vehicle(session, vehicle_id, lock=True)


def activate_agreement(
    session: Session,
    user: CurrentUser,
    agreement_id: int,
    *,
    settings: Settings,
    now: datetime | None = None,
    ip: str | None = None,
) -> Agreement:
    moment = now or clock.utc_now()
    require_rent_settings(session, moment)  # D20: before anything is locked or written
    agreement = lock_agreement(session, agreement_id)
    if agreement.status != "draft":
        raise _invalid_transition("activated", agreement.status)
    driver = get_driver(session, agreement.driver_id, lock=True)
    vehicle = _lock_vehicle(session, agreement.vehicle_id)

    result = assess(
        session,
        driver,
        vehicle,
        agreement.start_date,
        settings=settings,
        now=moment,
        exclude_id=agreement.id,
    )
    result.reasons = visible_reasons(user, driver, result.reasons)
    if result.reasons:
        raise AppError(
            "NOT_ELIGIBLE",
            "This agreement cannot start: " + " ".join(result.details()["messages"].values()),
            details=result.details(),
        )

    agreement.status = "active"
    agreement.activated_by = user.id
    agreement.activated_at = moment
    vehicle.status = "rented"
    try:
        session.flush()
    except IntegrityError as exc:  # rule 2 in the database: a concurrent change slipped through
        raise AppError(
            "AGREEMENT_OVERLAP",
            "This driver or auto already has an agreement for these dates.",
        ) from exc
    write_audit(
        session,
        action="agreement.activated",
        entity_type="agreement",
        entity_id=agreement.id,
        actor_id=user.id,
        before={"status": "draft", "vehicle_status": "available"},
        after={
            "status": "active",
            "agreement_no": agreement.agreement_no,
            "driver_id": driver.id,
            "vehicle_id": vehicle.id,
            "vehicle_status": "rented",
            "start_date": agreement.start_date,
            "daily_rent_paise": agreement.daily_rent_paise,
        },
        ip=ip,
    )
    return agreement


# --- End and cancel -------------------------------------------------------------------------------


def end_agreement(
    session: Session,
    user: CurrentUser,
    agreement_id: int,
    data: AgreementEnd,
    *,
    now: datetime | None = None,
    ip: str | None = None,
) -> EndResult:
    moment = now or clock.utc_now()
    today = business_date(moment)
    agreement = lock_agreement(session, agreement_id)
    if agreement.status != "active":
        raise _invalid_transition("ended", agreement.status)
    if data.end_date < agreement.start_date or data.end_date > today:
        raise AppError(
            "END_DATE_NOT_ALLOWED",
            "The return date must be between the start date and today.",
            details={"earliest": agreement.start_date.isoformat(), "latest": today.isoformat()},
        )
    vehicle = _lock_vehicle(session, agreement.vehicle_id)

    agreement.status = "ended"
    agreement.end_date = data.end_date
    agreement.ended_by = user.id
    agreement.ended_at = moment
    agreement.end_reason = data.reason
    previous_vehicle_status = vehicle.status
    if vehicle.status == "rented":
        vehicle.status = "available"
    session.flush()

    # D52: days already charged after the return day keep their charge; each gets a pending
    # waiver of its full net charge for the owner to decide.
    figures = charge_figures(moment)
    late = session.execute(
        select(RentCharge, figures.c.charge + figures.c.adjustments)
        .join(figures, figures.c.charge_id == RentCharge.id)
        .where(RentCharge.agreement_id == agreement.id, RentCharge.rent_date > data.end_date)
        .order_by(RentCharge.rent_date)
    ).all()
    reason = late_return_reason(data.end_date)
    waivers = [
        add_adjustment(
            session,
            charge,
            amount=-int(net),
            reason=reason,
            requested_by=user.id,
            now=moment,
            ip=ip,
            check=False,  # the owner's decision checks it against what is paid by then
        )
        for charge, net in late
        if net > 0
    ]
    write_audit(
        session,
        action="agreement.ended",
        entity_type="agreement",
        entity_id=agreement.id,
        actor_id=user.id,
        before={"status": "active", "vehicle_status": previous_vehicle_status},
        after={
            "status": "ended",
            "end_date": data.end_date,
            "vehicle_id": vehicle.id,
            "vehicle_status": vehicle.status,
            "waivers_created": len(waivers),
        },
        reason=data.reason,
        ip=ip,
    )
    return EndResult(agreement, waivers, data.end_date + timedelta(days=1))


def cancel_agreement(
    session: Session,
    user: CurrentUser,
    agreement_id: int,
    data: AgreementCancel,
    *,
    now: datetime | None = None,
    ip: str | None = None,
) -> Agreement:
    agreement = lock_agreement(session, agreement_id)
    if agreement.status != "draft":
        raise _invalid_transition("cancelled", agreement.status)
    agreement.status = "cancelled"
    agreement.cancelled_by = user.id
    agreement.cancelled_at = now or clock.utc_now()
    agreement.cancel_reason = data.reason
    session.flush()
    write_audit(
        session,
        action="agreement.cancelled",
        entity_type="agreement",
        entity_id=agreement.id,
        actor_id=user.id,
        before={"status": "draft"},
        after={"status": "cancelled"},
        reason=data.reason,
        ip=ip,
    )
    return agreement


# --- Signed copy ----------------------------------------------------------------------------------


def upload_signed_copy(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    agreement_id: int,
    *,
    data: bytes,
    ip: str | None,
) -> Agreement:
    agreement = lock_agreement(session, agreement_id)
    if agreement.status == "cancelled":
        raise _invalid_transition("given a signed copy", agreement.status)
    document = store_document(
        session,
        settings,
        data=data,
        owner_type="agreement",
        owner_id=agreement.id,
        doc_type="signed_agreement",
        uploaded_by=user.id,
    )
    previous = agreement.signed_document_id
    agreement.signed_document_id = document.id
    session.flush()
    write_audit(
        session,
        action="agreement.signed_copy_uploaded",
        entity_type="agreement",
        entity_id=agreement.id,
        actor_id=user.id,
        before={"signed_document_id": previous},
        after={"signed_document_id": document.id, "mime_type": document.mime_type},
        ip=ip,
    )
    return agreement


# --- Reading --------------------------------------------------------------------------------------


def get_agreement(session: Session, agreement_id: int) -> Agreement:
    agreement = session.get(Agreement, agreement_id)
    if agreement is None:
        raise not_found()
    return agreement


def agreements_out(session: Session, agreements: list[Agreement]) -> list[AgreementOut]:
    if not agreements:
        return []
    drivers = {
        d.id: d
        for d in session.scalars(
            select(Driver).where(Driver.id.in_({a.driver_id for a in agreements}))
        )
    }
    vehicles = {
        v.id: v
        for v in session.scalars(
            select(Vehicle).where(Vehicle.id.in_({a.vehicle_id for a in agreements}))
        )
    }
    ids: list[int | None] = []
    for a in agreements:
        ids += [a.created_by, a.activated_by, a.ended_by, a.cancelled_by]
    ids += [d.managed_by for d in drivers.values()]
    refs = user_refs(session, ids)

    def ref(user_id: int | None) -> Any:
        return refs.get(user_id) if user_id is not None else None

    out = []
    for a in agreements:
        d, v = drivers[a.driver_id], vehicles[a.vehicle_id]
        out.append(
            AgreementOut(
                id=a.id,
                agreement_no=a.agreement_no,
                status=a.status,  # type: ignore[arg-type]
                driver=DriverBrief(
                    id=d.id, code=d.code, full_name=d.full_name, managed_by=ref(d.managed_by)
                ),
                vehicle=VehicleBrief(
                    id=v.id,
                    registration_number=v.registration_number,
                    make=v.make,
                    model=v.model,
                    status=v.status,
                ),
                start_date=a.start_date,
                end_date=a.end_date,
                daily_rent_paise=a.daily_rent_paise,
                advance_required_paise=a.advance_required_paise,
                terms_version=a.terms_version,
                signed_document_id=a.signed_document_id,
                created_by=ref(a.created_by),
                created_at=a.created_at,
                activated_by=ref(a.activated_by),
                activated_at=a.activated_at,
                ended_by=ref(a.ended_by),
                ended_at=a.ended_at,
                end_reason=a.end_reason,
                cancelled_by=ref(a.cancelled_by),
                cancelled_at=a.cancelled_at,
                cancel_reason=a.cancel_reason,
                vehicle_available_from=(
                    a.end_date + timedelta(days=1)
                    if a.status == "ended" and a.end_date is not None
                    else None
                ),
            )
        )
    return out


def agreement_out(session: Session, agreement: Agreement) -> AgreementOut:
    return agreements_out(session, [agreement])[0]


def list_agreements(
    session: Session,
    params: PageParams,
    *,
    status: str | None = None,
    driver_id: int | None = None,
    vehicle_id: int | None = None,
    search: str | None = None,
) -> Page[AgreementOut]:
    statement = select(Agreement)
    if status:
        statement = statement.where(Agreement.status == status)
    if driver_id is not None:
        statement = statement.where(Agreement.driver_id == driver_id)
    if vehicle_id is not None:
        statement = statement.where(Agreement.vehicle_id == vehicle_id)
    if search:
        term = search.strip().upper()
        statement = statement.where(
            or_(
                Agreement.agreement_no == term,
                Agreement.driver_id.in_(select(Driver.id).where(Driver.code == term)),
                Agreement.vehicle_id.in_(
                    select(Vehicle.id).where(
                        Vehicle.registration_number == term.replace(" ", "").replace("-", "")
                    )
                ),
            )
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(Agreement.id.desc()).offset(params.offset).limit(params.page_size)
    ).all()
    return Page(
        items=agreements_out(session, list(rows)),
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def active_agreement_for_driver(session: Session, driver_id: int) -> Agreement | None:
    return session.scalars(
        select(Agreement).where(Agreement.driver_id == driver_id, Agreement.status == "active")
    ).one_or_none()


def print_agreement(
    session: Session, agreement: Agreement, *, now: datetime | None = None
) -> bytes:
    """The placeholder agreement PDF (Q13). No masked field is printed (D55)."""
    current = get_current_settings(session, now or clock.utc_now())
    driver = session.get(Driver, agreement.driver_id)
    vehicle = session.get(Vehicle, agreement.vehicle_id)
    if driver is None or vehicle is None:
        raise not_found()
    return render_agreement_pdf(
        AgreementSheet(
            business_name=(current.business_name if current else None) or "Auto rental business",
            business_address=current.business_address if current else None,
            agreement_no=agreement.agreement_no,
            status=agreement.status,
            driver_name=driver.full_name,
            driver_code=driver.code,
            driver_mobile=driver.mobile,
            registration_number=vehicle.registration_number,
            make_model=f"{vehicle.make} {vehicle.model}",
            daily_rent_paise=agreement.daily_rent_paise,
            advance_required_paise=agreement.advance_required_paise,
            start_date=agreement.start_date,
            end_date=agreement.end_date,
            terms_version=agreement.terms_version,
            printed_on=business_date(now),
        )
    )
