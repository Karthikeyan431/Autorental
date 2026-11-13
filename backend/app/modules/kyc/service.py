"""KYC by manual review (docs/kyc.md; rules 7, 9, 12; decisions D33-D37).

Statuses per attempt: draft -> submitted -> (under_review) -> approved | rejected |
resubmission_required; approved -> expired (licence job). Every change writes a `kyc_events` row
and an audit entry in the caller's transaction.

* Consent (purpose `kyc`, not withdrawn) is required before any attempt: CONSENT_REQUIRED.
* A new attempt may start when there is none, or the current one is `resubmission_required` or
  `expired`. `approved` and `rejected` change only through an owner reopen (answer 2).
* Reopen (owner only) creates the next attempt in `under_review` with the details copied; the
  previous attempt keeps its status and history and is no longer current (rule 12, D4).
* Approval needs every required checklist item ticked; the identity checklist includes "Only the
  last 4 digits of the Aadhaar number are visible".
* Only the owner, the managing staff member and staff with drivers.edit_any see a driver's KYC;
  everyone else gets 404. From Week 4 (D46), capture, documents and decisions are for the
  owner and the current manager only (app.modules.drivers.access).
* Masked values (licence number, dates of birth, gender) are never returned or audited; the
  licence date of birth is encrypted at rest like the licence number (D45, D46).
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import Settings
from app.core.crypto import field_cipher
from app.core.errors import AppError
from app.core.identifiers import LicenceHasher, normalise_licence_number
from app.core.pagination import LIKE_ESCAPE, Page, PageParams, escape_like
from app.core.permissions import CurrentUser
from app.core.time import business_date, utc_now
from app.modules.documents.models import Document
from app.modules.documents.schemas import document_out
from app.modules.documents.service import store_document
from app.modules.drivers import pii
from app.modules.drivers.access import (
    can_capture_kyc,
    can_decide_kyc,
    is_owner_or_manager,
    not_found,
    require_kyc,
    require_kyc_decide,
    require_kyc_edit,
)
from app.modules.drivers.models import Consent, Driver
from app.modules.drivers.service import get_driver, user_refs
from app.modules.kyc.eligibility import Eligibility, check_eligibility
from app.modules.kyc.models import (
    IdentityDetails,
    KycCheck,
    KycEvent,
    LicenceDetails,
)
from app.modules.kyc.schemas import (
    AttemptOut,
    ChecklistItem,
    ConsentOut,
    DriverKycOut,
    IdentityDetailsIn,
    IdentityDetailsOut,
    KycEventOut,
    LicenceDetailsIn,
    LicenceDetailsOut,
    QueueCounts,
    QueueDriver,
    QueueItem,
)
from app.modules.settings.schemas import SettingsValues
from app.modules.settings.service import get_current_settings

# --- Fixed lists ----------------------------------------------------------------------------------

AVAILABLE_METHODS = {"manual"}  # Week 4 adds uidai_app_attested, uidai_qr, parivahan_lookup
DOC_TYPES_BY_CHECK = {
    "identity": ("id_front", "id_back"),
    "licence": ("licence_front", "licence_back"),
}
REQUIRED_DOCS = {"identity": ("id_front",), "licence": ("licence_front", "licence_back")}

CHECKLISTS: dict[str, list[ChecklistItem]] = {
    "identity": [
        ChecklistItem(
            key="last4_only_visible",
            label="Only the last 4 digits of the Aadhaar number are visible",
            required=True,
        ),
        ChecklistItem(
            key="photo_matches_person",
            label="The photo matches the person in front of you",
            required=True,
        ),
        ChecklistItem(
            key="details_match_document",
            label="The typed name, date of birth and last 4 digits match the document",
            required=True,
        ),
    ],
    "licence": [
        ChecklistItem(
            key="photo_matches_person",
            label="The photo on the licence matches the person in front of you",
            required=True,
        ),
        ChecklistItem(
            key="details_match_card",
            label="The typed details match the front and back of the card",
            required=True,
        ),
        ChecklistItem(
            key="classes_permitted",
            label="The vehicle classes allow driving an auto-rickshaw",
            required=True,
        ),
        ChecklistItem(key="valid_today", label="The licence is valid today", required=True),
        ChecklistItem(
            key="digilocker_cross_check",
            label="Also seen in the driver's DigiLocker or mParivahan app (optional)",
            required=False,
        ),
    ],
}

OPEN_STATUSES = ("draft", "submitted", "under_review")
DECIDABLE_STATUSES = ("submitted", "under_review")
REOPENABLE_STATUSES = ("approved", "rejected")
DECISION_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "resubmit": "resubmission_required",
}


# --- Helpers --------------------------------------------------------------------------------------


def _settings_values(session: Session) -> SettingsValues | None:
    current = get_current_settings(session)
    return SettingsValues.model_validate(current) if current is not None else None


def accepted_id_types(session: Session) -> list[str]:
    values = _settings_values(session)
    if values is not None:
        return list(values.accepted_id_types)
    return ["masked_aadhaar"]


def _licence_alert_days(session: Session) -> int:
    values = _settings_values(session)
    if values is not None:
        return values.licence_alert_days
    default: int = SettingsValues.model_fields["licence_alert_days"].default
    return default


def _event(
    session: Session,
    check: KycCheck,
    *,
    from_status: str | None,
    to_status: str,
    actor_id: int | None,
    reason: str | None = None,
) -> None:
    session.add(
        KycEvent(
            kyc_check_id=check.id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor_id,
            at=utc_now(),
            reason=reason,
        )
    )


def _get_attempt(session: Session, attempt_id: int, *, lock: bool = False) -> KycCheck:
    statement = select(KycCheck).where(KycCheck.id == attempt_id)
    if lock:
        statement = statement.with_for_update()
    check = session.scalars(statement).one_or_none()
    if check is None:
        raise not_found()
    return check


def _attempt_and_driver(
    session: Session, user: CurrentUser, attempt_id: int, *, edit: bool, lock: bool = False
) -> tuple[KycCheck, Driver]:
    check = _get_attempt(session, attempt_id, lock=lock)
    driver = get_driver(session, check.driver_id)
    if edit:
        require_kyc_edit(user, driver)
    else:
        require_kyc(user, driver)
    return check, driver


def _require_draft(check: KycCheck) -> None:
    if check.status != "draft":
        raise AppError(
            "ATTEMPT_NOT_EDITABLE",
            "This attempt was already submitted. Start a new attempt to change it.",
        )


def _has_kyc_consent(session: Session, driver_id: int) -> bool:
    return (
        session.scalar(
            select(Consent.id)
            .where(
                Consent.driver_id == driver_id,
                Consent.purpose == "kyc",
                Consent.withdrawn_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


# --- Output ---------------------------------------------------------------------------------------


def _mask(last4: str) -> str:
    return "•" * 6 + last4


def attempts_out(session: Session, checks: list[KycCheck]) -> list[AttemptOut]:
    if not checks:
        return []
    ids = [c.id for c in checks]
    # A reopened attempt shows the documents of the attempts it came from.
    lineage: dict[int, list[int]] = {}
    by_id = {c.id: c for c in checks}
    for check in checks:
        chain = [check.id]
        parent = check.reopened_from_id
        while parent is not None:
            chain.append(parent)
            parent_check = by_id.get(parent) or session.get(KycCheck, parent)
            parent = parent_check.reopened_from_id if parent_check is not None else None
        lineage[check.id] = chain
    all_ids = {i for chain in lineage.values() for i in chain}

    identity = {
        d.kyc_check_id: d
        for d in session.scalars(
            select(IdentityDetails).where(IdentityDetails.kyc_check_id.in_(ids))
        )
    }
    licence = {
        d.kyc_check_id: d
        for d in session.scalars(select(LicenceDetails).where(LicenceDetails.kyc_check_id.in_(ids)))
    }
    documents: dict[int, list[Document]] = {}
    for document in session.scalars(
        select(Document)
        .where(
            Document.owner_type == "kyc_check",
            Document.owner_id.in_(all_ids),
            Document.purged_at.is_(None),
        )
        .order_by(Document.id)
    ):
        documents.setdefault(document.owner_id, []).append(document)
    events: dict[int, list[KycEvent]] = {}
    for event in session.scalars(
        select(KycEvent).where(KycEvent.kyc_check_id.in_(ids)).order_by(KycEvent.id)
    ):
        events.setdefault(event.kyc_check_id, []).append(event)
    refs = user_refs(
        session,
        [c.reviewed_by for c in checks]
        + [c.created_by for c in checks]
        + [e.actor_id for evs in events.values() for e in evs],
    )

    result: list[AttemptOut] = []
    for check in checks:
        idd = identity.get(check.id)
        lic = licence.get(check.id)
        docs = [d for i in lineage[check.id] for d in documents.get(i, [])]
        result.append(
            AttemptOut(
                id=check.id,
                driver_id=check.driver_id,
                check_type=check.check_type,
                attempt_no=check.attempt_no,
                method=check.method,
                status=check.status,
                is_current=check.is_current,
                is_simulated=check.is_simulated,
                submitted_at=check.submitted_at,
                reviewed_by=refs.get(check.reviewed_by) if check.reviewed_by else None,
                reviewed_at=check.reviewed_at,
                decision_reason=check.decision_reason,
                review_checklist=check.review_checklist,
                reopened_from_id=check.reopened_from_id,
                created_by=refs.get(check.created_by) if check.created_by else None,
                created_at=check.created_at,
                identity_details=(
                    IdentityDetailsOut(
                        document_type=idd.document_type,
                        id_last4=idd.id_last4,
                        name_on_document=idd.name_on_document,
                        masked_fields=[
                            name
                            for name, value in (
                                ("id_dob_or_yob", idd.dob_or_yob),
                                ("id_gender", idd.gender),
                            )
                            if value
                        ],
                    )
                    if idd is not None
                    else None
                ),
                licence_details=(
                    LicenceDetailsOut(
                        licence_number_masked=_mask(lic.licence_number_last4),
                        name_on_licence=lic.name_on_licence,
                        masked_fields=["licence_number"]
                        + (["licence_date_of_birth"] if lic.date_of_birth else []),
                        issue_date=lic.issue_date,
                        valid_until_non_transport=lic.valid_until_non_transport,
                        valid_until_transport=lic.valid_until_transport,
                        valid_until=lic.valid_until(),
                        vehicle_classes=list(lic.vehicle_classes),
                        issuing_authority=lic.issuing_authority,
                    )
                    if lic is not None
                    else None
                ),
                documents=[document_out(d) for d in docs],
                events=[
                    KycEventOut(
                        id=e.id,
                        from_status=e.from_status,
                        to_status=e.to_status,
                        actor=refs.get(e.actor_id) if e.actor_id else None,
                        at=e.at,
                        reason=e.reason,
                    )
                    for e in events.get(check.id, [])
                ],
                checklist=CHECKLISTS[check.check_type],
                required_documents=list(REQUIRED_DOCS[check.check_type]),
            )
        )
    return result


def attempt_out(session: Session, check: KycCheck) -> AttemptOut:
    return attempts_out(session, [check])[0]


def consent_out(session: Session, consent: Consent) -> ConsentOut:
    refs = user_refs(session, (consent.captured_by, consent.withdrawn_by))
    return ConsentOut(
        id=consent.id,
        driver_id=consent.driver_id,
        purpose=consent.purpose,
        notice_version=consent.notice_version,
        method=consent.method,
        captured_by=refs[consent.captured_by],
        captured_at=consent.captured_at,
        withdrawn_at=consent.withdrawn_at,
        withdrawn_by=refs.get(consent.withdrawn_by) if consent.withdrawn_by else None,
        withdrawal_reason=consent.withdrawal_reason,
    )


def driver_kyc(session: Session, user: CurrentUser, driver_id: int) -> DriverKycOut:
    driver = get_driver(session, driver_id)
    require_kyc(user, driver)
    checks = list(
        session.scalars(
            select(KycCheck)
            .where(KycCheck.driver_id == driver.id)
            .order_by(KycCheck.check_type, KycCheck.attempt_no.desc())
        ).all()
    )
    outs = attempts_out(session, checks)
    current = {o.check_type: o for o in outs if o.is_current}
    consents = session.scalars(
        select(Consent).where(Consent.driver_id == driver.id).order_by(Consent.id.desc())
    ).all()
    return DriverKycOut(
        driver_id=driver.id,
        identity=current.get("identity"),
        licence=current.get("licence"),
        history=outs,
        consents=[consent_out(session, c) for c in consents],
        has_kyc_consent=_has_kyc_consent(session, driver.id),
        accepted_id_types=accepted_id_types(session),
        can_reveal=is_owner_or_manager(user, driver),
        can_capture=can_capture_kyc(user, driver),
        can_decide=can_decide_kyc(user, driver),
        can_view_documents=is_owner_or_manager(user, driver),
    )


def get_attempt(session: Session, user: CurrentUser, attempt_id: int) -> AttemptOut:
    check, _ = _attempt_and_driver(session, user, attempt_id, edit=False)
    return attempt_out(session, check)


# --- Consent --------------------------------------------------------------------------------------


def record_consent(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    *,
    purpose: str,
    notice_version: str,
    method: str,
    ip: str | None,
) -> Consent:
    driver = get_driver(session, driver_id)
    require_kyc_edit(user, driver)
    consent = Consent(
        driver_id=driver.id,
        purpose=purpose,
        notice_version=notice_version,
        method=method,
        captured_by=user.id,
        captured_at=utc_now(),
    )
    session.add(consent)
    session.flush()
    write_audit(
        session,
        action="consent.recorded",
        entity_type="consent",
        entity_id=consent.id,
        actor_id=user.id,
        after={
            "driver_id": driver.id,
            "purpose": purpose,
            "notice_version": notice_version,
            "method": method,
        },
        ip=ip,
    )
    return consent


def withdraw_consent(
    session: Session, user: CurrentUser, consent_id: int, *, reason: str | None, ip: str | None
) -> Consent:
    consent = session.scalars(
        select(Consent).where(Consent.id == consent_id).with_for_update()
    ).one_or_none()
    if consent is None:
        raise not_found()
    driver = get_driver(session, consent.driver_id)
    require_kyc_edit(user, driver)
    if consent.withdrawn_at is not None:
        raise AppError("CONSENT_ALREADY_WITHDRAWN", "This consent was already withdrawn.")
    consent.withdrawn_at = utc_now()
    consent.withdrawn_by = user.id
    consent.withdrawal_reason = reason
    session.flush()
    write_audit(
        session,
        action="consent.withdrawn",
        entity_type="consent",
        entity_id=consent.id,
        actor_id=user.id,
        after={"driver_id": driver.id, "purpose": consent.purpose},
        reason=reason,
        ip=ip,
    )
    return consent


# --- Attempts -------------------------------------------------------------------------------------


def start_attempt(
    session: Session,
    user: CurrentUser,
    driver_id: int,
    *,
    check_type: str,
    method: str,
    ip: str | None,
) -> KycCheck:
    driver = get_driver(session, driver_id, lock=True)
    require_kyc_edit(user, driver)
    if method not in AVAILABLE_METHODS:
        raise AppError("KYC_METHOD_NOT_AVAILABLE", "This verification method is not available yet.")
    if not _has_kyc_consent(session, driver.id):
        raise AppError(
            "CONSENT_REQUIRED",
            "Record the driver's consent before any KYC step.",
        )
    current = session.scalars(
        select(KycCheck)
        .where(
            KycCheck.driver_id == driver.id,
            KycCheck.check_type == check_type,
            KycCheck.is_current,
        )
        .with_for_update()
    ).one_or_none()
    if current is not None:
        if current.status in OPEN_STATUSES:
            raise AppError(
                "KYC_ATTEMPT_OPEN",
                "There is already an open attempt for this check.",
                details={"attempt_id": current.id},
            )
        if current.status in REOPENABLE_STATUSES:
            raise AppError(
                "KYC_REOPEN_REQUIRED",
                "This check was decided. Only the owner can reopen it.",
                details={"attempt_id": current.id},
            )
        current.is_current = False  # resubmission_required or expired
        session.flush()

    last_no = session.scalar(
        select(func.max(KycCheck.attempt_no)).where(
            KycCheck.driver_id == driver.id, KycCheck.check_type == check_type
        )
    )
    check = KycCheck(
        driver_id=driver.id,
        check_type=check_type,
        attempt_no=(last_no or 0) + 1,
        method=method,
        status="draft",
        is_current=True,
        created_by=user.id,
    )
    session.add(check)
    session.flush()
    _event(session, check, from_status=None, to_status="draft", actor_id=user.id)
    write_audit(
        session,
        action="kyc.attempt_created",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        after={
            "driver_id": driver.id,
            "check_type": check_type,
            "attempt_no": check.attempt_no,
            "method": method,
            "status": "draft",
        },
        ip=ip,
    )
    return check


def save_identity_details(
    session: Session,
    user: CurrentUser,
    attempt_id: int,
    data: IdentityDetailsIn,
    *,
    ip: str | None,
) -> KycCheck:
    check, _ = _attempt_and_driver(session, user, attempt_id, edit=True, lock=True)
    if check.check_type != "identity":
        raise AppError("WRONG_CHECK_TYPE", "This attempt is not an identity check.")
    _require_draft(check)
    if data.document_type not in accepted_id_types(session):
        raise AppError(
            "ID_TYPE_NOT_ACCEPTED",
            "This ID document is not accepted. The owner sets accepted documents in Settings.",
        )
    details = session.scalars(
        select(IdentityDetails).where(IdentityDetails.kyc_check_id == check.id)
    ).one_or_none()
    values = data.model_dump()
    # Masked fields left blank keep the saved value (N17).
    for key in ("dob_or_yob", "gender"):
        if values[key] is None and details is not None:
            values[key] = getattr(details, key)
    if values["dob_or_yob"] is None:
        raise AppError(
            "FIELD_REQUIRED", "Enter the date or year of birth on the document.", status_code=422
        )
    if details is None:
        details = IdentityDetails(kyc_check_id=check.id, **values)
        session.add(details)
    else:
        for key, value in values.items():
            setattr(details, key, value)
    session.flush()
    write_audit(
        session,
        action="kyc.details_saved",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        after={"document_type": data.document_type},
        ip=ip,
    )
    return check


def save_licence_details(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    attempt_id: int,
    data: LicenceDetailsIn,
    *,
    ip: str | None,
) -> KycCheck:
    check, driver = _attempt_and_driver(session, user, attempt_id, edit=True, lock=True)
    if check.check_type != "licence":
        raise AppError("WRONG_CHECK_TYPE", "This attempt is not a licence check.")
    _require_draft(check)
    details = session.scalars(
        select(LicenceDetails).where(LicenceDetails.kyc_check_id == check.id)
    ).one_or_none()
    values: dict[str, Any] = data.model_dump(exclude={"licence_number", "date_of_birth"})
    values["driver_id"] = driver.id
    # Masked fields left blank keep the saved value (N17).
    if data.date_of_birth is not None:
        values["date_of_birth"] = pii.encrypt_licence_dob(settings, driver.id, data.date_of_birth)
    elif details is None:
        values["date_of_birth"] = None
    if data.licence_number is None:
        if details is None:
            raise AppError("FIELD_REQUIRED", "Enter the licence number.", status_code=422)
        _store_licence_details(session, check, details, values)
        _audit_licence_details(session, user, check, data, ip=ip)
        return check
    try:
        number = normalise_licence_number(data.licence_number)
    except ValueError as exc:
        raise AppError("INVALID_LICENCE_NUMBER", str(exc), status_code=422) from exc
    try:
        hasher = LicenceHasher(settings.LOOKUP_HMAC_KEY.get_secret_value())
    except ValueError as exc:  # development .env from before Week 3 (production refuses to start)
        raise AppError(
            "LOOKUP_KEY_NOT_CONFIGURED",
            "Licence checks are not configured: run scripts\\db-setup.ps1 to add LOOKUP_HMAC_KEY.",
            status_code=503,
        ) from exc
    number_hash = hasher.hash(number)
    taken = session.scalar(
        select(LicenceDetails.id)
        .where(
            LicenceDetails.licence_number_hash == number_hash,
            LicenceDetails.driver_id != driver.id,
        )
        .limit(1)
    )
    if taken is not None:
        raise AppError("LICENCE_TAKEN", "This licence number is already registered to a driver.")

    values.update(
        licence_number=field_cipher(settings).encrypt(
            number, context=pii.licence_number_context(driver.id)
        ),
        licence_number_hash=number_hash,
        licence_number_last4=number[-4:],
    )
    _store_licence_details(session, check, details, values)
    _audit_licence_details(session, user, check, data, ip=ip)
    return check


def _store_licence_details(
    session: Session, check: KycCheck, details: LicenceDetails | None, values: dict[str, Any]
) -> None:
    if details is None:
        session.add(LicenceDetails(kyc_check_id=check.id, **values))
    else:
        for key, value in values.items():
            setattr(details, key, value)
    try:
        with session.begin_nested():
            session.flush()
    except Exception as exc:  # the exclusion constraint, if two requests race
        if "ex_licence_details_one_driver_per_licence" in str(exc):
            raise AppError(
                "LICENCE_TAKEN", "This licence number is already registered to a driver."
            ) from exc
        raise


def _audit_licence_details(
    session: Session, user: CurrentUser, check: KycCheck, data: LicenceDetailsIn, *, ip: str | None
) -> None:
    """Only visible fields (validity, classes) are recorded; never the licence number or the
    date of birth (D45)."""
    write_audit(
        session,
        action="kyc.details_saved",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        after={
            "valid_until_non_transport": data.valid_until_non_transport,
            "valid_until_transport": data.valid_until_transport,
            "vehicle_classes": data.vehicle_classes,
        },
        ip=ip,
    )


def upload_attempt_document(
    session: Session,
    settings: Settings,
    user: CurrentUser,
    attempt_id: int,
    *,
    doc_type: str,
    data: bytes,
    ip: str | None,
) -> Document:
    check, _ = _attempt_and_driver(session, user, attempt_id, edit=True, lock=True)
    if doc_type not in DOC_TYPES_BY_CHECK[check.check_type]:
        raise AppError(
            "DOC_TYPE_NOT_ALLOWED",
            "This document does not belong to this check.",
            status_code=422,
        )
    _require_draft(check)
    document = store_document(
        session,
        settings,
        data=data,
        owner_type="kyc_check",
        owner_id=check.id,
        doc_type=doc_type,
        uploaded_by=user.id,
    )
    write_audit(
        session,
        action="kyc.document_uploaded",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        after={"document_id": document.id, "doc_type": doc_type, "mime_type": document.mime_type},
        ip=ip,
    )
    return document


def submit_attempt(
    session: Session, user: CurrentUser, attempt_id: int, *, ip: str | None
) -> KycCheck:
    check, _ = _attempt_and_driver(session, user, attempt_id, edit=True, lock=True)
    if check.status != "draft":
        raise AppError("KYC_INVALID_TRANSITION", "Only a draft can be submitted.")
    missing: list[str] = []
    model = IdentityDetails if check.check_type == "identity" else LicenceDetails
    if session.scalar(select(model.id).where(model.kyc_check_id == check.id)) is None:
        missing.append("details")
    uploaded = set(
        session.scalars(
            select(Document.doc_type).where(
                Document.owner_type == "kyc_check", Document.owner_id == check.id
            )
        )
    )
    missing += [d for d in REQUIRED_DOCS[check.check_type] if d not in uploaded]
    if missing:
        raise AppError(
            "KYC_INCOMPLETE",
            "Complete the details and upload the required documents first.",
            details={"missing": missing},
        )
    check.status = "submitted"
    check.submitted_at = utc_now()
    session.flush()
    _event(session, check, from_status="draft", to_status="submitted", actor_id=user.id)
    write_audit(
        session,
        action="kyc.submitted",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        before={"status": "draft"},
        after={"status": "submitted"},
        ip=ip,
    )
    return check


def decide_attempt(
    session: Session,
    user: CurrentUser,
    attempt_id: int,
    *,
    decision: str,
    checklist: dict[str, bool],
    reason: str | None,
    ip: str | None,
) -> KycCheck:
    check, driver = _attempt_and_driver(session, user, attempt_id, edit=False, lock=True)
    require_kyc_decide(user, driver)
    if not check.is_current or check.status not in DECIDABLE_STATUSES:
        raise AppError(
            "KYC_INVALID_TRANSITION", "Only a submitted attempt can be approved or rejected."
        )
    items = CHECKLISTS[check.check_type]
    known = {item.key for item in items}
    unknown = sorted(set(checklist) - known)
    if unknown:
        raise AppError(
            "CHECKLIST_UNKNOWN_ITEM",
            "The checklist has items that do not belong to this check.",
            status_code=422,
            details={"unknown": unknown},
        )
    if decision == "approve":
        missing = [i.key for i in items if i.required and checklist.get(i.key) is not True]
        if missing:
            raise AppError(
                "CHECKLIST_INCOMPLETE",
                "Tick every required checklist item before approving.",
                details={"missing": missing},
            )
    elif not reason:
        raise AppError(
            "REASON_REQUIRED",
            "Give a reason when rejecting or asking for documents again.",
            status_code=422,
        )

    previous = check.status
    new_status = DECISION_STATUS[decision]
    check.status = new_status
    check.review_checklist = {k: bool(checklist[k]) for k in sorted(checklist)}
    check.reviewed_by = user.id
    check.reviewed_at = utc_now()
    check.decision_reason = reason
    session.flush()
    _event(
        session, check, from_status=previous, to_status=new_status, actor_id=user.id, reason=reason
    )
    write_audit(
        session,
        action="kyc.decided",
        entity_type="kyc_check",
        entity_id=check.id,
        actor_id=user.id,
        before={"status": previous},
        after={"status": new_status, "checklist": check.review_checklist},
        reason=reason,
        ip=ip,
    )
    return check


def reopen_attempt(
    session: Session, owner: CurrentUser, attempt_id: int, *, reason: str, ip: str | None
) -> KycCheck:
    old = _get_attempt(session, attempt_id, lock=True)
    get_driver(session, old.driver_id, lock=True)
    if not old.is_current or old.status not in REOPENABLE_STATUSES:
        raise AppError(
            "KYC_INVALID_TRANSITION", "Only the current approved or rejected attempt can reopen."
        )
    old.is_current = False
    session.flush()
    last_no = session.scalar(
        select(func.max(KycCheck.attempt_no)).where(
            KycCheck.driver_id == old.driver_id, KycCheck.check_type == old.check_type
        )
    )
    new = KycCheck(
        driver_id=old.driver_id,
        check_type=old.check_type,
        attempt_no=(last_no or 0) + 1,
        method=old.method,
        status="under_review",
        is_simulated=old.is_simulated,
        evidence=dict(old.evidence),
        submitted_at=old.submitted_at,
        is_current=True,
        reopened_from_id=old.id,
        created_by=owner.id,
    )
    session.add(new)
    session.flush()

    # Copy the details so the reviewer and eligibility see them on the new attempt.
    if old.check_type == "identity":
        source_id = session.scalars(
            select(IdentityDetails).where(IdentityDetails.kyc_check_id == old.id)
        ).one_or_none()
        if source_id is not None:
            session.add(
                IdentityDetails(
                    kyc_check_id=new.id,
                    document_type=source_id.document_type,
                    id_last4=source_id.id_last4,
                    name_on_document=source_id.name_on_document,
                    dob_or_yob=source_id.dob_or_yob,
                    gender=source_id.gender,
                    qr_signature_valid=source_id.qr_signature_valid,
                    photo_match_confirmed_by=source_id.photo_match_confirmed_by,
                )
            )
    else:
        source_lic = session.scalars(
            select(LicenceDetails).where(LicenceDetails.kyc_check_id == old.id)
        ).one_or_none()
        if source_lic is not None:
            session.add(
                LicenceDetails(
                    kyc_check_id=new.id,
                    driver_id=source_lic.driver_id,
                    licence_number=source_lic.licence_number,
                    licence_number_hash=source_lic.licence_number_hash,
                    licence_number_last4=source_lic.licence_number_last4,
                    name_on_licence=source_lic.name_on_licence,
                    date_of_birth=source_lic.date_of_birth,
                    issue_date=source_lic.issue_date,
                    valid_until_non_transport=source_lic.valid_until_non_transport,
                    valid_until_transport=source_lic.valid_until_transport,
                    vehicle_classes=list(source_lic.vehicle_classes),
                    issuing_authority=source_lic.issuing_authority,
                    lookup_status_text=source_lic.lookup_status_text,
                    looked_up_at=source_lic.looked_up_at,
                    lookup_screenshot_document_id=source_lic.lookup_screenshot_document_id,
                )
            )
    session.flush()
    _event(
        session, new, from_status=None, to_status="under_review", actor_id=owner.id, reason=reason
    )
    write_audit(
        session,
        action="kyc.reopened",
        entity_type="kyc_check",
        entity_id=new.id,
        actor_id=owner.id,
        before={"attempt_id": old.id, "status": old.status},
        after={"attempt_id": new.id, "attempt_no": new.attempt_no, "status": "under_review"},
        reason=reason,
        ip=ip,
    )
    return new


# --- Eligibility ----------------------------------------------------------------------------------


def eligibility(
    session: Session, settings: Settings, user: CurrentUser, driver_id: int, on_date: date | None
) -> tuple[Eligibility, date]:
    driver = get_driver(session, driver_id)
    require_kyc(user, driver)
    day = on_date or business_date()
    return check_eligibility(session, driver, day, settings=settings), day


# --- Queue (rule 9) -------------------------------------------------------------------------------


def _queue_subquery(session: Session, user: CurrentUser) -> Any:
    today = business_date()
    horizon = today + timedelta(days=_licence_alert_days(session))
    selects = []
    for check_type in ("identity", "licence"):
        valid_until = func.coalesce(
            LicenceDetails.valid_until_transport, LicenceDetails.valid_until_non_transport
        )
        bucket = case(
            (or_(KycCheck.id.is_(None), KycCheck.status == "draft"), "pending"),
            (KycCheck.status.in_(DECIDABLE_STATUSES), "under_review"),
            (KycCheck.status == "resubmission_required", "resubmission"),
            (KycCheck.status == "rejected", "rejected"),
            (KycCheck.status == "expired", "expiring"),
            (
                and_(
                    KycCheck.status == "approved",
                    literal(check_type) == "licence",
                    valid_until.is_not(None),
                    valid_until <= horizon,
                ),
                "expiring",
            ),
            else_="done",
        )
        statement = (
            select(
                Driver.id.label("driver_id"),
                Driver.code.label("code"),
                Driver.full_name.label("full_name"),
                Driver.managed_by.label("managed_by"),
                cast(literal(check_type), String).label("check_type"),
                KycCheck.id.label("attempt_id"),
                KycCheck.attempt_no.label("attempt_no"),
                KycCheck.status.label("status"),
                KycCheck.submitted_at.label("submitted_at"),
                KycCheck.updated_at.label("updated_at"),
                valid_until.label("licence_valid_until"),
                bucket.label("bucket"),
            )
            .select_from(Driver)
            .outerjoin(
                KycCheck,
                and_(
                    KycCheck.driver_id == Driver.id,
                    KycCheck.check_type == check_type,
                    KycCheck.is_current,
                ),
            )
            .outerjoin(LicenceDetails, LicenceDetails.kyc_check_id == KycCheck.id)
        )
        # D46: staff (edit_any included) see only the drivers they manage; the owner sees all.
        if not user.is_owner:
            statement = statement.where(Driver.managed_by == user.id)
        selects.append(statement)
    return union_all(*selects).subquery("queue")


def queue(
    session: Session,
    user: CurrentUser,
    params: PageParams,
    *,
    bucket: str,
    check_type: str | None,
    search: str | None,
) -> Page[QueueItem]:
    q = _queue_subquery(session, user)
    statement = select(q).where(q.c.bucket == bucket)
    if check_type:
        statement = statement.where(q.c.check_type == check_type)
    if search:
        pattern = f"%{escape_like(search.strip())}%"
        statement = statement.where(
            or_(
                q.c.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                q.c.code.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    order = (
        [q.c.licence_valid_until.asc().nulls_last(), q.c.driver_id]
        if bucket == "expiring"
        else [q.c.submitted_at.asc().nulls_last(), q.c.driver_id, q.c.check_type]
    )
    rows = session.execute(
        statement.order_by(*order).offset(params.offset).limit(params.page_size)
    ).all()
    refs = user_refs(session, [r.managed_by for r in rows])
    return Page(
        items=[
            QueueItem(
                driver=QueueDriver(
                    id=r.driver_id,
                    code=r.code,
                    full_name=r.full_name,
                    managed_by=refs[r.managed_by],
                ),
                check_type=r.check_type,
                bucket=r.bucket,
                attempt_id=r.attempt_id,
                attempt_no=r.attempt_no,
                status=r.status,
                submitted_at=r.submitted_at,
                updated_at=r.updated_at,
                licence_valid_until=r.licence_valid_until,
            )
            for r in rows
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def queue_counts(session: Session, user: CurrentUser) -> QueueCounts:
    q = _queue_subquery(session, user)
    counts: dict[str, int] = {
        bucket: total
        for bucket, total in session.execute(
            select(q.c.bucket, func.count()).group_by(q.c.bucket)
        ).all()
    }
    return QueueCounts(
        pending=counts.get("pending", 0),
        under_review=counts.get("under_review", 0),
        resubmission=counts.get("resubmission", 0),
        rejected=counts.get("rejected", 0),
        expiring=counts.get("expiring", 0),
    )
