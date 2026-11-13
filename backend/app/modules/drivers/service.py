"""Drivers: registration, edits, the managing staff member (rule 14), restrictions, status and
the activity timeline. Access rules live in app.modules.drivers.access.

Audit entries never contain names, mobiles, addresses or dates of birth: only ids, codes,
statuses and the names of the fields that changed.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog, write_audit
from app.core.config import Settings
from app.core.errors import AppError
from app.core.pagination import LIKE_ESCAPE, Page, PageParams, escape_like
from app.core.permissions import CurrentUser
from app.core.time import utc_now
from app.modules.documents.models import Document
from app.modules.documents.service import store_document
from app.modules.drivers.access import (
    can_edit,
    can_see_kyc,
    not_found,
    require_edit,
    sees_all_kyc,
)
from app.modules.drivers.models import (
    Consent,
    Driver,
    DriverManagerHistory,
    DriverRestriction,
)
from app.modules.drivers.schemas import (
    DriverCreate,
    DriverListItem,
    DriverOut,
    DriverUpdate,
    ManagerHistoryOut,
    RestrictionOut,
    TimelineEntry,
    UserRef,
)
from app.modules.kyc.models import KycCheck
from app.modules.users.models import User

PHOTO_MAX_SIDE = 1600
_TIMELINE_LIMIT = 200


# --- Lookups ------------------------------------------------------------------------------------


def user_refs(session: Session, ids: Iterable[int | None]) -> dict[int, UserRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = session.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {row.id: UserRef(id=row.id, name=row.name) for row in rows}


def get_driver(session: Session, driver_id: int, *, lock: bool = False) -> Driver:
    statement = select(Driver).where(Driver.id == driver_id)
    if lock:
        statement = statement.with_for_update()
    driver = session.scalars(statement).one_or_none()
    if driver is None:
        raise not_found()
    return driver


def current_statuses(session: Session, driver_ids: Iterable[int]) -> dict[tuple[int, str], str]:
    ids = list(driver_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(KycCheck.driver_id, KycCheck.check_type, KycCheck.status).where(
            KycCheck.driver_id.in_(ids), KycCheck.is_current
        )
    )
    return {(r.driver_id, r.check_type): r.status for r in rows}


def driver_out(session: Session, user: CurrentUser, driver: Driver) -> DriverOut:
    refs = user_refs(session, (driver.created_by, driver.managed_by))
    since = session.scalar(
        select(DriverManagerHistory.from_at).where(
            DriverManagerHistory.driver_id == driver.id, DriverManagerHistory.to_at.is_(None)
        )
    )
    sees_kyc = can_see_kyc(user, driver)
    statuses = current_statuses(session, [driver.id]) if sees_kyc else {}
    return DriverOut(
        id=driver.id,
        code=driver.code,
        full_name=driver.full_name,
        mobile=driver.mobile,
        alt_mobile=driver.alt_mobile,
        address=driver.address,
        date_of_birth=driver.date_of_birth,
        emergency_name=driver.emergency_name,
        emergency_mobile=driver.emergency_mobile,
        photo_document_id=driver.photo_document_id,
        account_status=driver.account_status,
        status_reason=driver.status_reason,
        payment_rhythm=driver.payment_rhythm,
        registered_at=driver.registered_at,
        created_by=refs[driver.created_by],
        managed_by=refs[driver.managed_by],
        managed_since=since,
        identity_status=statuses.get((driver.id, "identity")),
        licence_status=statuses.get((driver.id, "licence")),
        can_edit=can_edit(user, driver),
        can_view_kyc=sees_kyc,
    )


# --- Create and edit ------------------------------------------------------------------------------


def _mobile_taken() -> AppError:
    return AppError("MOBILE_TAKEN", "Another driver already uses this mobile number.")


def _ensure_mobile_free(session: Session, mobile: str, exclude_id: int | None = None) -> None:
    statement = select(Driver.id).where(Driver.mobile == mobile)
    if exclude_id is not None:
        statement = statement.where(Driver.id != exclude_id)
    if session.scalar(statement.limit(1)) is not None:
        raise _mobile_taken()


def _flush_or_mobile_taken(session: Session) -> None:
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        if "uq_drivers_mobile" in str(exc.orig):
            raise _mobile_taken() from exc
        raise


def create_driver(
    session: Session, user: CurrentUser, data: DriverCreate, *, ip: str | None
) -> Driver:
    _ensure_mobile_free(session, data.mobile)
    now = utc_now()
    driver = Driver(
        **data.model_dump(),
        created_by=user.id,
        managed_by=user.id,
        registered_at=now,
    )
    session.add(driver)
    _flush_or_mobile_taken(session)
    session.refresh(driver, ["code"])
    session.add(
        DriverManagerHistory(driver_id=driver.id, staff_id=user.id, from_at=now, changed_by=user.id)
    )
    write_audit(
        session,
        action="driver.created",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=user.id,
        after={
            "code": driver.code,
            "account_status": driver.account_status,
            "payment_rhythm": driver.payment_rhythm,
            "created_by": user.id,
            "managed_by": user.id,
        },
        ip=ip,
    )
    return driver


def update_driver(
    session: Session, user: CurrentUser, driver_id: int, changes: DriverUpdate, *, ip: str | None
) -> Driver:
    driver = get_driver(session, driver_id, lock=True)
    require_edit(user, driver)
    values = changes.model_dump(exclude_unset=True)
    for required in ("full_name", "mobile", "address", "date_of_birth", "payment_rhythm"):
        if required in values and values[required] is None:
            raise AppError("FIELD_REQUIRED", f"{required} cannot be empty.", status_code=422)
    changed = sorted(k for k, v in values.items() if getattr(driver, k) != v)
    if not changed:
        return driver
    if "mobile" in changed:
        _ensure_mobile_free(session, values["mobile"], exclude_id=driver.id)
    before_rhythm = driver.payment_rhythm
    for key in changed:
        setattr(driver, key, values[key])
    _flush_or_mobile_taken(session)
    audit_after: dict[str, Any] = {"fields": changed}
    audit_before: dict[str, Any] | None = None
    if "payment_rhythm" in changed:
        audit_before = {"payment_rhythm": before_rhythm}
        audit_after["payment_rhythm"] = driver.payment_rhythm
    write_audit(
        session,
        action="driver.updated",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=user.id,
        before=audit_before,
        after=audit_after,
        ip=ip,
    )
    return driver


def set_photo(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    driver_id: int,
    data: bytes,
    *,
    ip: str | None,
) -> Driver:
    driver = get_driver(session, driver_id, lock=True)
    require_edit(user, driver)
    document = store_document(
        session,
        settings,
        data=data,
        owner_type="driver",
        owner_id=driver.id,
        doc_type="driver_photo",
        uploaded_by=user.id,
        max_side=PHOTO_MAX_SIDE,
    )
    previous = driver.photo_document_id
    driver.photo_document_id = document.id
    session.flush()
    write_audit(
        session,
        action="driver.photo_uploaded",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=user.id,
        before={"photo_document_id": previous},
        after={"photo_document_id": document.id},
        ip=ip,
    )
    return driver


# --- Manager (rule 14) ----------------------------------------------------------------------------


def change_manager(
    session: Session,
    owner: CurrentUser,
    driver_id: int,
    *,
    staff_id: int,
    reason: str,
    ip: str | None,
) -> Driver:
    driver = get_driver(session, driver_id, lock=True)
    target = session.get(User, staff_id)
    if target is None or not target.is_active:
        raise AppError(
            "MANAGER_NOT_AVAILABLE", "Choose an active staff member (or yourself) as manager."
        )
    if target.id == driver.managed_by:
        raise AppError("SAME_MANAGER", "This person already manages the driver.")

    now = utc_now()
    open_row = session.scalars(
        select(DriverManagerHistory)
        .where(DriverManagerHistory.driver_id == driver.id, DriverManagerHistory.to_at.is_(None))
        .with_for_update()
    ).one_or_none()
    if open_row is not None:
        open_row.to_at = now
        session.flush()
    previous = driver.managed_by
    driver.managed_by = target.id
    session.add(
        DriverManagerHistory(
            driver_id=driver.id,
            staff_id=target.id,
            from_at=now,
            changed_by=owner.id,
            reason=reason,
        )
    )
    session.flush()
    # Week 7: open escalations move to the new manager here (rule 14).
    write_audit(
        session,
        action="driver.manager_changed",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=owner.id,
        before={"managed_by": previous},
        after={"managed_by": target.id},
        reason=reason,
        ip=ip,
    )
    return driver


def manager_history(session: Session, driver_id: int) -> list[ManagerHistoryOut]:
    get_driver(session, driver_id)
    rows = session.scalars(
        select(DriverManagerHistory)
        .where(DriverManagerHistory.driver_id == driver_id)
        .order_by(DriverManagerHistory.from_at.desc(), DriverManagerHistory.id.desc())
    ).all()
    refs = user_refs(session, [r.staff_id for r in rows] + [r.changed_by for r in rows])
    return [
        ManagerHistoryOut(
            id=r.id,
            staff=refs[r.staff_id],
            from_at=r.from_at,
            to_at=r.to_at,
            changed_by=refs[r.changed_by],
            reason=r.reason,
        )
        for r in rows
    ]


def manager_options(session: Session) -> list[UserRef]:
    rows = session.execute(
        select(User.id, User.name).where(User.is_active).order_by(User.role.desc(), User.name)
    )
    return [UserRef(id=r.id, name=r.name) for r in rows]


# --- List -----------------------------------------------------------------------------------------


def list_drivers(
    session: Session,
    user: CurrentUser,
    params: PageParams,
    *,
    search: str | None,
    status: str | None,
    managed_by: int | None,
    mine: bool,
    kyc: str | None,
) -> Page[DriverListItem]:
    statement = select(Driver)
    if search:
        pattern = f"%{escape_like(search.strip())}%"
        statement = statement.where(
            or_(
                Driver.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                Driver.code.ilike(pattern, escape=LIKE_ESCAPE),
                Driver.mobile.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    if status:
        statement = statement.where(Driver.account_status == status)
    if managed_by is not None:
        statement = statement.where(Driver.managed_by == managed_by)
    if mine:
        statement = statement.where(Driver.managed_by == user.id)
    if kyc is not None:
        # The KYC filter only ever reveals drivers whose KYC this user may see.
        if not sees_all_kyc(user):
            statement = statement.where(Driver.managed_by == user.id)
        approved = [
            select(KycCheck.id)
            .where(
                KycCheck.driver_id == Driver.id,
                KycCheck.check_type == check_type,
                KycCheck.is_current,
                KycCheck.status == "approved",
            )
            .exists()
            for check_type in ("identity", "licence")
        ]
        both = and_(*approved)
        statement = statement.where(both if kyc == "verified" else ~both)

    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    drivers = session.scalars(
        statement.order_by(Driver.id.desc()).offset(params.offset).limit(params.page_size)
    ).all()
    refs = user_refs(session, [d.created_by for d in drivers] + [d.managed_by for d in drivers])
    visible = [d.id for d in drivers if can_see_kyc(user, d)]
    statuses = current_statuses(session, visible)
    return Page(
        items=[
            DriverListItem(
                id=d.id,
                code=d.code,
                full_name=d.full_name,
                mobile=d.mobile,
                account_status=d.account_status,
                photo_document_id=d.photo_document_id,
                created_by=refs[d.created_by],
                managed_by=refs[d.managed_by],
                identity_status=statuses.get((d.id, "identity")),
                licence_status=statuses.get((d.id, "licence")),
            )
            for d in drivers
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


# --- Status and restrictions ----------------------------------------------------------------------


def set_account_status(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    *,
    status: str,
    reason: str | None,
    ip: str | None,
) -> Driver:
    driver = get_driver(session, driver_id, lock=True)
    if driver.account_status == status:
        raise AppError("DRIVER_STATUS_UNCHANGED", f"The driver is already {status}.")
    previous = driver.account_status
    driver.account_status = status
    driver.status_reason = reason
    session.flush()
    write_audit(
        session,
        action="driver.suspended" if status == "suspended" else "driver.reactivated",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=user.id,
        before={"account_status": previous},
        after={"account_status": status},
        reason=reason,
        ip=ip,
    )
    return driver


def restriction_out(session: Session, restriction: DriverRestriction) -> RestrictionOut:
    refs = user_refs(session, (restriction.placed_by, restriction.lifted_by))
    return RestrictionOut(
        id=restriction.id,
        driver_id=restriction.driver_id,
        reason=restriction.reason,
        is_blocking=restriction.is_blocking,
        placed_by=refs[restriction.placed_by],
        placed_at=restriction.placed_at,
        lifted_by=refs.get(restriction.lifted_by) if restriction.lifted_by else None,
        lifted_at=restriction.lifted_at,
        lift_reason=restriction.lift_reason,
    )


def place_restriction(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    *,
    reason: str,
    is_blocking: bool,
    ip: str | None,
) -> DriverRestriction:
    driver = get_driver(session, driver_id, lock=True)
    restriction = DriverRestriction(
        driver_id=driver.id,
        reason=reason,
        is_blocking=is_blocking,
        placed_by=user.id,
        placed_at=utc_now(),
    )
    session.add(restriction)
    session.flush()
    write_audit(
        session,
        action="driver.restriction_placed",
        entity_type="driver",
        entity_id=driver.id,
        actor_id=user.id,
        after={"restriction_id": restriction.id, "is_blocking": is_blocking},
        reason=reason,
        ip=ip,
    )
    return restriction


def list_restrictions(session: Session, driver_id: int) -> list[DriverRestriction]:
    get_driver(session, driver_id)
    return list(
        session.scalars(
            select(DriverRestriction)
            .where(DriverRestriction.driver_id == driver_id)
            .order_by(DriverRestriction.placed_at.desc(), DriverRestriction.id.desc())
        ).all()
    )


def lift_restriction(
    session: Session,
    user: CurrentUser,
    restriction_id: int,
    *,
    reason: str | None,
    ip: str | None,
) -> DriverRestriction:
    restriction = session.scalars(
        select(DriverRestriction).where(DriverRestriction.id == restriction_id).with_for_update()
    ).one_or_none()
    if restriction is None:
        raise not_found()
    if restriction.lifted_at is not None:
        raise AppError("RESTRICTION_ALREADY_LIFTED", "This restriction was already lifted.")
    restriction.lifted_at = utc_now()
    restriction.lifted_by = user.id
    restriction.lift_reason = reason
    session.flush()
    write_audit(
        session,
        action="driver.restriction_lifted",
        entity_type="driver",
        entity_id=restriction.driver_id,
        actor_id=user.id,
        after={"restriction_id": restriction.id},
        reason=reason,
        ip=ip,
    )
    return restriction


# --- Timeline -------------------------------------------------------------------------------------


def timeline(session: Session, user: CurrentUser, driver_id: int) -> list[TimelineEntry]:
    """The driver's activity from the audit log. KYC entries (consents, attempts, documents) only
    for users who may see this driver's KYC."""
    driver = get_driver(session, driver_id)
    conditions = [and_(AuditLog.entity_type == "driver", AuditLog.entity_id == driver.id)]
    if can_see_kyc(user, driver):
        check_ids = select(KycCheck.id).where(KycCheck.driver_id == driver.id)
        consent_ids = select(Consent.id).where(Consent.driver_id == driver.id)
        document_ids = select(Document.id).where(
            or_(
                and_(Document.owner_type == "driver", Document.owner_id == driver.id),
                and_(Document.owner_type == "kyc_check", Document.owner_id.in_(check_ids)),
            )
        )
        conditions += [
            and_(AuditLog.entity_type == "kyc_check", AuditLog.entity_id.in_(check_ids)),
            and_(AuditLog.entity_type == "consent", AuditLog.entity_id.in_(consent_ids)),
            and_(AuditLog.entity_type == "document", AuditLog.entity_id.in_(document_ids)),
        ]
    entries = session.scalars(
        select(AuditLog).where(or_(*conditions)).order_by(AuditLog.id.desc()).limit(_TIMELINE_LIMIT)
    ).all()
    refs = user_refs(session, [e.actor_id for e in entries])
    return [
        TimelineEntry(
            id=e.id,
            at=e.occurred_at,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            actor=refs.get(e.actor_id) if e.actor_id is not None else None,
            reason=e.reason,
            before=e.before,
            after=e.after,
        )
        for e in entries
    ]
