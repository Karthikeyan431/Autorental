"""Autos, papers and maintenance (Week 4; docs/data-model.md; Q29).

* Registration numbers are unique after normalising (VEHICLE_REGISTRATION_TAKEN; the unique
  constraint backs it).
* Staff move an auto between available, maintenance and inactive. `rented` is set only by the
  agreements service (Week 5): asking for it gives VEHICLE_STATUS_NOT_ALLOWED, and a rented
  auto cannot be moved here (VEHICLE_RENTED).
* `require_selectable_vehicle` is the check agreement creation uses (Week 5): only an available
  auto can be chosen (VEHICLE_NOT_AVAILABLE).
* Papers: every record is kept; the latest `valid_until` of each kind is current. Insurance,
  fitness and permit raise `vehicle_paper_expiring` / `vehicle_paper_expired` alerts (Q29),
  as soon as a paper is saved and from the daily job. Alert messages hold the registration
  number, the kind and the date only.
* Every write has a permission check in the router, one transaction and an audit entry.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import LIKE_ESCAPE, Page, PageParams, escape_like
from app.core.permissions import CurrentUser
from app.core.time import business_date
from app.modules.alerts.models import Alert
from app.modules.documents.models import Document
from app.modules.documents.service import store_document
from app.modules.drivers.access import not_found
from app.modules.drivers.service import user_refs
from app.modules.settings.schemas import SettingsValues
from app.modules.settings.service import get_current_settings
from app.modules.vehicles.models import MaintenanceRecord, Vehicle, VehicleCompliance
from app.modules.vehicles.schemas import (
    MaintenanceCreate,
    MaintenanceOut,
    PaperOut,
    PaperState,
    StatusChange,
    VehicleCreate,
    VehicleOut,
    VehicleSummary,
    VehicleUpdate,
)

# Q29 default: the papers that raise expiry alerts. Pollution is recorded but does not alert.
ALERT_KINDS = ("insurance", "fitness", "permit")
STAFF_STATUSES = ("available", "maintenance", "inactive")


def vehicle_alert_days(session: Session) -> int:
    current = get_current_settings(session)
    if current is not None:
        return int(current.vehicle_alert_days)
    default: int = SettingsValues.model_fields["vehicle_alert_days"].default
    return default


def paper_state(valid_until: date, today: date, alert_days: int) -> PaperState:
    if valid_until < today:
        return "expired"
    if valid_until <= today + timedelta(days=alert_days):
        return "expiring"
    return "ok"


def get_vehicle(session: Session, vehicle_id: int, *, lock: bool = False) -> Vehicle:
    statement = select(Vehicle).where(Vehicle.id == vehicle_id)
    if lock:
        # Re-read after waiting for the lock, so a row already in the session is never stale.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    vehicle = session.scalars(statement).one_or_none()
    if vehicle is None:
        raise not_found()
    return vehicle


def current_papers(session: Session, vehicle_ids: list[int]) -> dict[int, list[VehicleCompliance]]:
    """The latest paper of each kind per vehicle, in kind order."""
    result: dict[int, dict[str, VehicleCompliance]] = {}
    if not vehicle_ids:
        return {}
    rows = session.scalars(
        select(VehicleCompliance)
        .where(VehicleCompliance.vehicle_id.in_(vehicle_ids))
        .order_by(VehicleCompliance.valid_until, VehicleCompliance.id)
    )
    for paper in rows:  # later rows win
        result.setdefault(paper.vehicle_id, {})[paper.kind] = paper
    order = {"insurance": 0, "fitness": 1, "permit": 2, "pollution": 3}
    return {
        vid: sorted(papers.values(), key=lambda p: order[p.kind]) for vid, papers in result.items()
    }


def _paper_out(
    paper: VehicleCompliance,
    today: date,
    alert_days: int,
    refs: dict[int, Any],
    mimes: dict[int, str],
) -> PaperOut:
    return PaperOut(
        id=paper.id,
        kind=paper.kind,
        number=paper.number,
        valid_from=paper.valid_from,
        valid_until=paper.valid_until,
        document_id=paper.document_id,
        document_mime_type=mimes.get(paper.document_id) if paper.document_id else None,
        state=paper_state(paper.valid_until, today, alert_days),
        recorded_by=refs.get(paper.recorded_by) if paper.recorded_by else None,
        created_at=paper.created_at,
    )


def _mime_types(session: Session, papers: list[VehicleCompliance]) -> dict[int, str]:
    ids = [p.document_id for p in papers if p.document_id is not None]
    if not ids:
        return {}
    rows = session.execute(select(Document.id, Document.mime_type).where(Document.id.in_(ids)))
    return {row.id: row.mime_type for row in rows}


def vehicles_out(session: Session, vehicles: list[Vehicle]) -> list[VehicleOut]:
    today = business_date()
    alert_days = vehicle_alert_days(session)
    papers = current_papers(session, [v.id for v in vehicles])
    refs = user_refs(
        session,
        [v.created_by for v in vehicles] + [p.recorded_by for ps in papers.values() for p in ps],
    )
    mimes = _mime_types(session, [p for ps in papers.values() for p in ps])
    return [
        VehicleOut(
            id=v.id,
            registration_number=v.registration_number,
            make=v.make,
            model=v.model,
            year=v.year,
            fuel_type=v.fuel_type,
            status=v.status,
            selectable=v.status == "available",
            notes=v.notes,
            papers=[_paper_out(p, today, alert_days, refs, mimes) for p in papers.get(v.id, [])],
            created_by=refs.get(v.created_by) if v.created_by else None,
            created_at=v.created_at,
        )
        for v in vehicles
    ]


def vehicle_out(session: Session, vehicle: Vehicle) -> VehicleOut:
    return vehicles_out(session, [vehicle])[0]


def list_vehicles(
    session: Session, params: PageParams, *, status: str | None, search: str | None
) -> Page[VehicleOut]:
    statement = select(Vehicle)
    if status:
        statement = statement.where(Vehicle.status == status)
    if search:
        pattern = f"%{escape_like(search.strip())}%"
        compact = f"%{escape_like(search.replace(' ', '').replace('-', '').upper())}%"
        statement = statement.where(
            or_(
                Vehicle.registration_number.like(compact, escape=LIKE_ESCAPE),
                Vehicle.make.ilike(pattern, escape=LIKE_ESCAPE),
                Vehicle.model.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = session.scalars(
        statement.order_by(Vehicle.registration_number)
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return Page(
        items=vehicles_out(session, list(rows)),
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def _registration_taken() -> AppError:
    return AppError(
        "VEHICLE_REGISTRATION_TAKEN", "An auto with this registration number already exists."
    )


def _flush_unique(session: Session) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if "uq_vehicles_registration_number" in str(exc):
            raise _registration_taken() from exc
        raise


def create_vehicle(
    session: Session, user: CurrentUser, data: VehicleCreate, *, ip: str | None
) -> Vehicle:
    if session.scalar(
        select(Vehicle.id).where(Vehicle.registration_number == data.registration_number)
    ):
        raise _registration_taken()
    vehicle = Vehicle(**data.model_dump(), status="available", created_by=user.id)
    session.add(vehicle)
    _flush_unique(session)
    write_audit(
        session,
        action="vehicle.created",
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_id=user.id,
        after={**data.model_dump(), "status": "available"},
        ip=ip,
    )
    return vehicle


def update_vehicle(
    session: Session, user: CurrentUser, vehicle_id: int, data: VehicleUpdate, *, ip: str | None
) -> Vehicle:
    vehicle = get_vehicle(session, vehicle_id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("registration_number") is None:
        changes.pop("registration_number", None)
    for key in ("make", "model"):  # required columns: null means "unchanged"
        if key in changes and changes[key] is None:
            changes.pop(key)
    before = {k: getattr(vehicle, k) for k in changes}
    changed = {k: v for k, v in changes.items() if before[k] != v}
    if not changed:
        return vehicle
    if "registration_number" in changed and session.scalar(
        select(Vehicle.id).where(
            Vehicle.registration_number == changed["registration_number"],
            Vehicle.id != vehicle.id,
        )
    ):
        raise _registration_taken()
    for key, value in changed.items():
        setattr(vehicle, key, value)
    _flush_unique(session)
    write_audit(
        session,
        action="vehicle.updated",
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_id=user.id,
        before={k: before[k] for k in changed},
        after=changed,
        ip=ip,
    )
    return vehicle


def change_status(
    session: Session, user: CurrentUser, vehicle_id: int, data: StatusChange, *, ip: str | None
) -> Vehicle:
    vehicle = get_vehicle(session, vehicle_id, lock=True)
    if data.status not in STAFF_STATUSES:
        raise AppError(
            "VEHICLE_STATUS_NOT_ALLOWED",
            "An auto becomes rented only when an agreement starts.",
        )
    if vehicle.status == "rented":
        raise AppError(
            "VEHICLE_RENTED", "This auto is rented. End its agreement to change its status."
        )
    if vehicle.status == data.status:
        raise AppError("VEHICLE_STATUS_UNCHANGED", "The auto already has this status.")
    previous = vehicle.status
    vehicle.status = data.status
    session.flush()
    write_audit(
        session,
        action="vehicle.status_changed",
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_id=user.id,
        before={"status": previous},
        after={"status": data.status},
        reason=data.reason,
        ip=ip,
    )
    return vehicle


def require_selectable_vehicle(session: Session, vehicle_id: int) -> Vehicle:
    """For agreement creation (Week 5): lock the auto and refuse unless it is available."""
    vehicle = get_vehicle(session, vehicle_id, lock=True)
    if vehicle.status != "available":
        raise AppError(
            "VEHICLE_NOT_AVAILABLE",
            "This auto is not available (rented, in maintenance or inactive).",
            details={"status": vehicle.status},
        )
    return vehicle


# --- Papers ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperInput:
    kind: str
    number: str | None
    valid_from: date | None
    valid_until: date


def add_paper(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    vehicle_id: int,
    data: PaperInput,
    *,
    file: bytes | None,
    ip: str | None,
) -> VehicleCompliance:
    vehicle = get_vehicle(session, vehicle_id, lock=True)
    document_id: int | None = None
    if file is not None:
        document = store_document(
            session,
            settings,
            data=file,
            owner_type="vehicle",
            owner_id=vehicle.id,
            doc_type="vehicle_paper",
            uploaded_by=user.id,
        )
        document_id = document.id
    paper = VehicleCompliance(
        vehicle_id=vehicle.id,
        kind=data.kind,
        number=data.number,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        document_id=document_id,
        recorded_by=user.id,
    )
    session.add(paper)
    session.flush()
    write_audit(
        session,
        action="vehicle.paper_added",
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_id=user.id,
        after={
            "paper_id": paper.id,
            "kind": data.kind,
            "valid_from": data.valid_from,
            "valid_until": data.valid_until,
            "document_id": document_id,
        },
        ip=ip,
    )
    # Alert at once, not only at the next daily run.
    raise_paper_alerts(
        session, business_date(), alert_days=vehicle_alert_days(session), vehicle_id=vehicle.id
    )
    return paper


def list_papers(session: Session, vehicle_id: int) -> list[PaperOut]:
    get_vehicle(session, vehicle_id)
    papers = list(
        session.scalars(
            select(VehicleCompliance)
            .where(VehicleCompliance.vehicle_id == vehicle_id)
            .order_by(VehicleCompliance.kind, VehicleCompliance.valid_until.desc())
        )
    )
    today, alert_days = business_date(), vehicle_alert_days(session)
    refs = user_refs(session, [p.recorded_by for p in papers])
    mimes = _mime_types(session, papers)
    return [_paper_out(p, today, alert_days, refs, mimes) for p in papers]


def raise_paper_alerts(
    session: Session, today: date, *, alert_days: int, vehicle_id: int | None = None
) -> int:
    """One alert per current paper (Q29 kinds) within the window or expired. Idempotent: the
    dedupe key names the paper and its date. Inactive autos are skipped."""
    statement = select(Vehicle).where(Vehicle.status != "inactive")
    if vehicle_id is not None:
        statement = statement.where(Vehicle.id == vehicle_id)
    vehicles = {v.id: v for v in session.scalars(statement)}
    created = 0
    papers_by_vehicle = current_papers(session, list(vehicles))
    for vid in sorted(papers_by_vehicle):  # stable order: by auto, then kind
        for paper in papers_by_vehicle[vid]:
            if paper.kind not in ALERT_KINDS:
                continue
            state = paper_state(paper.valid_until, today, alert_days)
            if state == "ok":
                continue
            kind = "vehicle_paper_expired" if state == "expired" else "vehicle_paper_expiring"
            until = paper.valid_until.isoformat()
            registration = vehicles[vid].registration_number
            message = (
                f"Auto {registration}: {paper.kind} expired after {until}."
                if state == "expired"
                else f"Auto {registration}: {paper.kind} valid until {until}."
            )
            inserted = session.execute(
                insert(Alert)
                .values(
                    kind=kind,
                    entity_type="vehicle",
                    entity_id=vid,
                    severity="critical" if state == "expired" else "warning",
                    message=message,
                    dedupe_key=f"{kind}:{paper.id}:{until}",
                )
                .on_conflict_do_nothing(index_elements=[Alert.dedupe_key])
                .returning(Alert.id)
            ).scalar_one_or_none()
            created += inserted is not None
    session.flush()
    return created


def summary(session: Session) -> VehicleSummary:
    counts = dict(
        session.execute(select(Vehicle.status, func.count()).group_by(Vehicle.status)).all()
    )
    today, alert_days = business_date(), vehicle_alert_days(session)
    active = list(session.scalars(select(Vehicle.id).where(Vehicle.status != "inactive")))
    states = [
        paper_state(p.valid_until, today, alert_days)
        for papers in current_papers(session, active).values()
        for p in papers
        if p.kind in ALERT_KINDS
    ]
    return VehicleSummary(
        available=counts.get("available", 0),
        rented=counts.get("rented", 0),
        maintenance=counts.get("maintenance", 0),
        inactive=counts.get("inactive", 0),
        papers_expiring=states.count("expiring"),
        papers_expired=states.count("expired"),
    )


# --- Maintenance ----------------------------------------------------------------------------------


def _maintenance_out(record: MaintenanceRecord, refs: dict[int, Any]) -> MaintenanceOut:
    return MaintenanceOut(
        id=record.id,
        vehicle_id=record.vehicle_id,
        started_on=record.started_on,
        ended_on=record.ended_on,
        description=record.description,
        cost_paise=record.cost_paise,
        recorded_by=refs.get(record.recorded_by) if record.recorded_by else None,
        created_at=record.created_at,
    )


def add_maintenance(
    session: Session, user: CurrentUser, vehicle_id: int, data: MaintenanceCreate, *, ip: str | None
) -> MaintenanceOut:
    vehicle = get_vehicle(session, vehicle_id, lock=True)
    record = MaintenanceRecord(vehicle_id=vehicle.id, recorded_by=user.id, **data.model_dump())
    session.add(record)
    session.flush()
    write_audit(
        session,
        action="vehicle.maintenance_recorded",
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_id=user.id,
        after={"maintenance_id": record.id, **data.model_dump()},
        ip=ip,
    )
    return _maintenance_out(record, user_refs(session, [user.id]))


def list_maintenance(session: Session, vehicle_id: int) -> list[MaintenanceOut]:
    get_vehicle(session, vehicle_id)
    records = list(
        session.scalars(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.vehicle_id == vehicle_id)
            .order_by(MaintenanceRecord.started_on.desc(), MaintenanceRecord.id.desc())
        )
    )
    refs = user_refs(session, [r.recorded_by for r in records])
    return [_maintenance_out(r, refs) for r in records]
