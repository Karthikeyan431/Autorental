"""Pay requests (docs/rent-and-payments.md §2; rule 18; N3, N4, N5; D57).

* **Generation** (the job and the button) is idempotent. For each driver with an active
  agreement: a daily driver gets one request for today; a weekly driver one on the weekly pay
  day, for the 7 days ending that day (never before the agreement's start). The amount is the
  outstanding up to and including the period (rule 18), so never more than the rent due; no
  request when nothing is due. A period that already has a request is left alone; otherwise the
  driver's open request is marked `superseded` and the new one created, keeping one open request
  per driver (D57, C1). Each driver row is locked first, so the job and the button can run at the
  same time.
* **Status** (D57 decision 4): an open request becomes `paid` when the driver's outstanding up to
  its period end reaches 0, re-checked after anything that lowers outstanding (approval, credit
  applied, advance adjustment approved, waiver approved). After a rejection or a reversal the
  latest `paid` request returns to `open` if money is due again and no other request is open
  (D57, C2).
* **Sending**: staff tap Send on WhatsApp; the app records who, when and how many times. Nothing
  is sent by the server.
* Visibility follows D54: the owner, the driver's current manager and `reports.all`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.core.time import business_date, iso_weekday
from app.modules.agreements.models import Agreement
from app.modules.drivers.access import not_found
from app.modules.drivers.models import Driver
from app.modules.drivers.service import user_refs
from app.modules.pay_requests import links
from app.modules.pay_requests.models import PayRequest
from app.modules.pay_requests.schemas import DriverRef, PayRequestOut
from app.modules.payments.claims import oldest_unpaid
from app.modules.payments.models import Payment
from app.modules.rent.access import can_view_money
from app.modules.rent.ledger import driver_outstanding_through
from app.modules.settings.models import SettingsVersion
from app.modules.settings.service import get_current_settings

UPI_ID_NOT_SET = "UPI_ID_NOT_SET"
UPI_ID_MESSAGE = "Set the business UPI ID in Settings."
WEEK_DAYS = 7


@dataclass(frozen=True)
class GenerationResult:
    created: int
    superseded: int
    unchanged: int


def require_upi_settings(session: Session, now: datetime) -> SettingsVersion:
    current = get_current_settings(session, now)
    if current is None or not current.business_upi_id:
        raise AppError(UPI_ID_NOT_SET, UPI_ID_MESSAGE)
    return current


def open_request(session: Session, driver_id: int) -> PayRequest | None:
    return session.scalars(
        select(PayRequest).where(PayRequest.driver_id == driver_id, PayRequest.status == "open")
    ).one_or_none()


def _period(agreement: Agreement, driver: Driver, today: date, pay_day: int) -> date | None:
    """The period start for today, or None when this driver gets no request today."""
    if driver.payment_rhythm == "weekly":
        if iso_weekday(today) != pay_day:
            return None
        return max(today - timedelta(days=WEEK_DAYS - 1), agreement.start_date)
    return today


def _audit_status(
    session: Session, request: PayRequest, before: str, *, actor_id: int | None, now: datetime
) -> None:
    write_audit(
        session,
        action=f"pay_request.{request.status}",
        entity_type="pay_request",
        entity_id=request.id,
        actor_id=actor_id,
        before={"status": before},
        after={"status": request.status, "driver_id": request.driver_id},
        occurred_at=now,
    )


def generate_pay_requests(
    session: Session, *, now: datetime, actor_id: int | None = None, ip: str | None = None
) -> GenerationResult:
    """Create today's requests. The caller owns the transaction."""
    settings = require_upi_settings(session, now)
    today = business_date(now)
    agreements = session.execute(
        select(Agreement.id, Agreement.driver_id)
        .where(Agreement.status == "active", Agreement.start_date <= today)
        .order_by(Agreement.driver_id)
    ).all()
    created = superseded = unchanged = 0
    for agreement_id, driver_id in agreements:
        driver = session.scalars(
            select(Driver).where(Driver.id == driver_id).with_for_update()
        ).one()
        agreement = session.get(Agreement, agreement_id)
        if agreement is None or agreement.status != "active":
            continue
        period_start = _period(agreement, driver, today, settings.weekly_pay_day)
        if period_start is None:
            continue
        existing = session.scalar(
            select(func.count())
            .select_from(PayRequest)
            .where(
                PayRequest.driver_id == driver.id,
                PayRequest.period_start == period_start,
                PayRequest.status != "superseded",
            )
        )
        if existing:
            unchanged += 1
            continue
        amount = driver_outstanding_through(session, driver.id, today, now=now)
        if amount <= 0:
            continue
        previous = open_request(session, driver.id)
        if previous is not None:
            previous.status = "superseded"
            session.flush()
            _audit_status(session, previous, "open", actor_id=actor_id, now=now)
            superseded += 1
        suggested = oldest_unpaid(session, driver.id, amount, now=now)
        request = PayRequest(
            driver_id=driver.id,
            agreement_id=agreement.id,
            period_start=period_start,
            period_end=today,
            amount_paise=amount,
            reference_code=links.reference_code(driver.code, period_start),
            suggested_charge_ids=[day.charge_id for day, _ in suggested],
        )
        session.add(request)
        session.flush()
        write_audit(
            session,
            action="pay_request.created",
            entity_type="pay_request",
            entity_id=request.id,
            actor_id=actor_id,
            after={
                "driver_id": driver.id,
                "agreement_id": agreement.id,
                "period_start": period_start,
                "period_end": today,
                "amount_paise": amount,
                "reference_code": request.reference_code,
            },
            ip=ip,
            occurred_at=now,
        )
        created += 1
    return GenerationResult(created, superseded, unchanged)


def refresh_pay_request_status(
    session: Session, driver_id: int, *, now: datetime, actor_id: int | None = None
) -> None:
    """D57 decision 4 and C2. Called after every change that moves the driver's balance."""
    current = session.scalars(
        select(PayRequest)
        .where(PayRequest.driver_id == driver_id, PayRequest.status.in_(("open", "paid")))
        .order_by(PayRequest.period_start.desc(), PayRequest.id.desc())
        .limit(1)
        .with_for_update()
    ).one_or_none()
    if current is None:
        return
    due = driver_outstanding_through(session, driver_id, current.period_end, now=now)
    if current.status == "open" and due <= 0:
        current.status = "paid"
    elif current.status == "paid" and due > 0 and open_request(session, driver_id) is None:
        current.status = "open"
    else:
        return
    session.flush()
    _audit_status(
        session, current, "open" if current.status == "paid" else "paid", actor_id=actor_id, now=now
    )


def get_visible_request(session: Session, user: CurrentUser, request_id: int) -> PayRequest:
    request = session.get(PayRequest, request_id)
    if request is None:
        raise not_found()
    driver = session.get(Driver, request.driver_id)
    if driver is None or not can_view_money(user, driver):
        raise not_found()
    return request


def mark_sent(
    session: Session, user: CurrentUser, request_id: int, *, now: datetime, ip: str | None = None
) -> PayRequest:
    if not user.has(Permission.PAYREQUESTS_SEND):
        raise AppError("FORBIDDEN", "You do not have permission to do this.", status_code=403)
    get_visible_request(session, user, request_id)
    request = session.scalars(
        select(PayRequest)
        .where(PayRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    if request.status != "open":
        raise AppError(
            "PAY_REQUEST_NOT_OPEN",
            "This pay request is no longer open.",
            details={"status": request.status},
        )
    request.send_count += 1
    request.sent_by = user.id
    request.sent_at = now
    session.flush()
    write_audit(
        session,
        action="pay_request.sent",
        entity_type="pay_request",
        entity_id=request.id,
        actor_id=user.id,
        after={"driver_id": request.driver_id, "send_count": request.send_count},
        ip=ip,
        occurred_at=now,
    )
    return request


def requests_for_day(session: Session, day: date) -> list[PayRequest]:
    """The day's screen: requests for periods ending that day, and any still open."""
    return list(
        session.scalars(
            select(PayRequest)
            .where(
                PayRequest.status != "superseded",
                or_(PayRequest.period_end == day, PayRequest.status == "open"),
            )
            .order_by(PayRequest.id)
        )
    )


def list_pay_requests(
    session: Session,
    user: CurrentUser,
    day: date,
    *,
    driver_ids: list[int] | None,
    mine: bool = False,
) -> list[PayRequestOut]:
    rows = requests_for_day(session, day)
    if driver_ids is not None:
        allowed = set(driver_ids)
        rows = [r for r in rows if r.driver_id in allowed]
    out = pay_requests_out(session, rows)
    if mine:
        out = [r for r in out if r.managed_by.id == user.id]
    return sorted(out, key=lambda r: (r.status != "open", r.driver.code))


def pay_requests_out(session: Session, rows: list[PayRequest]) -> list[PayRequestOut]:
    if not rows:
        return []
    settings = get_current_settings(session)
    drivers = {
        d.id: d
        for d in session.scalars(select(Driver).where(Driver.id.in_({r.driver_id for r in rows})))
    }
    awaiting = dict(
        session.execute(
            select(Payment.pay_request_id, func.sum(Payment.amount_paise))
            .where(
                Payment.pay_request_id.in_([r.id for r in rows]),
                Payment.status == "awaiting_approval",
            )
            .group_by(Payment.pay_request_id)
        )
        .tuples()
        .all()
    )
    refs = user_refs(session, [d.managed_by for d in drivers.values()] + [r.sent_by for r in rows])
    upi_id = settings.business_upi_id if settings is not None else None
    business = (settings.business_name if settings is not None else None) or ""
    payee = (settings.upi_payee_name if settings is not None else None) or business or None
    template = settings.whatsapp_template if settings is not None else ""
    warn_above = settings.weekly_mdr_warning_paise if settings is not None else 200000
    out: list[PayRequestOut] = []
    for r in rows:
        driver = drivers[r.driver_id]
        link = (
            links.upi_link(
                upi_id=upi_id,
                payee_name=payee,
                amount_paise=r.amount_paise,
                reference_code=r.reference_code,
            )
            if upi_id
            else ""
        )
        message = links.render_message(
            template,
            name=driver.full_name,
            amount_paise=r.amount_paise,
            upi_link=link,
            reference_code=r.reference_code,
            business_name=business,
        )
        out.append(
            PayRequestOut(
                id=r.id,
                driver=DriverRef(id=driver.id, code=driver.code, full_name=driver.full_name),
                managed_by=refs[driver.managed_by],
                agreement_id=r.agreement_id,
                period_start=r.period_start,
                period_end=r.period_end,
                amount_paise=r.amount_paise,
                reference_code=r.reference_code,
                status=r.status,  # type: ignore[arg-type]
                send_count=r.send_count,
                sent_at=r.sent_at,
                sent_by=refs.get(r.sent_by) if r.sent_by is not None else None,
                upi_link=link,
                whatsapp_url=links.whatsapp_url(driver.mobile, message),
                mdr_warning=r.amount_paise > warn_above,
                awaiting_approval_paise=int(awaiting.get(r.id, 0) or 0),
                created_at=r.created_at,
            )
        )
    return out


def qr_for(session: Session, request: PayRequest) -> bytes:
    settings = get_current_settings(session)
    if settings is None or not settings.business_upi_id:
        raise AppError(UPI_ID_NOT_SET, UPI_ID_MESSAGE)
    payee = settings.upi_payee_name or settings.business_name
    return links.qr_png(
        links.upi_link(
            upi_id=settings.business_upi_id,
            payee_name=payee,
            amount_paise=request.amount_paise,
            reference_code=request.reference_code,
        )
    )
