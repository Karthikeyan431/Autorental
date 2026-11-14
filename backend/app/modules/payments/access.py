"""Who sees and works on payments (D57 decision 1; D54).

* **Recording**: any staff member with `payments.record`, for any driver (cash at the office
  while the manager is away). The recorder sees the payment they recorded and its status.
* **Seeing a payment**: the owner and `reports.all`, the driver's current manager, and the
  staff member who recorded it. Anyone else gets 404.
* **Confirming days and applying credit**: the money rule (owner, current manager,
  `reports.all`). A recorder who may see the payment but not the driver's money gets 403
  `DAYS_CONFIRM_NOT_ALLOWED`.
* Approving, rejecting and deciding reversals and advance: owner-only permissions.
"""

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.access import not_found
from app.modules.drivers.models import Driver
from app.modules.payments.models import Payment
from app.modules.rent.access import can_view_money, sees_all_money


def forbidden() -> AppError:
    return AppError("FORBIDDEN", "You do not have permission to do this.", status_code=403)


def require_permission(user: CurrentUser, permission: Permission) -> None:
    if not user.has(permission):
        raise forbidden()


def can_view_payment(user: CurrentUser, payment: Payment, driver: Driver) -> bool:
    return can_view_money(user, driver) or payment.recorded_by == user.id


def visible_payment(session: Session, user: CurrentUser, payment_id: int) -> tuple[Payment, Driver]:
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise not_found()
    driver = session.get(Driver, payment.driver_id)
    if driver is None or not can_view_payment(user, payment, driver):
        raise not_found()
    return payment, driver


def require_days_confirm(user: CurrentUser, driver: Driver) -> None:
    require_permission(user, Permission.PAYMENTS_RECORD)
    if not can_view_money(user, driver):
        raise AppError(
            "DAYS_CONFIRM_NOT_ALLOWED",
            "Only the owner or the driver's manager can confirm the days a payment covers.",
            status_code=403,
        )


def payment_scope(user: CurrentUser) -> Any | None:
    """A WHERE clause for the payments this user may list (None = every payment)."""
    if sees_all_money(user):
        return None
    managed = select(Driver.id).where(Driver.managed_by == user.id)
    return or_(Payment.driver_id.in_(managed), Payment.recorded_by == user.id)
