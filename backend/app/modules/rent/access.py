"""Who sees money figures (N1; Week 5 plan approval, D54).

* A driver's ledger and charge adjustments: the owner, the driver's **current** manager, and
  staff with `reports.all`. Anyone else gets 404, as for any record they may not see
  (docs/security.md); they still see the driver.
* The overdue list and the dashboard figures: business-wide for the owner and `reports.all`;
  otherwise only the drivers the staff member manages.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.access import not_found
from app.modules.drivers.models import Driver


def sees_all_money(user: CurrentUser) -> bool:
    return user.is_owner or user.has(Permission.REPORTS_ALL)


def can_view_money(user: CurrentUser, driver: Driver) -> bool:
    return sees_all_money(user) or driver.managed_by == user.id


def require_money_view(user: CurrentUser, driver: Driver) -> None:
    if not can_view_money(user, driver):
        raise not_found()


def money_scope(session: Session, user: CurrentUser) -> list[int] | None:
    """None = every driver; otherwise the ids of the drivers this staff member manages."""
    if sees_all_money(user):
        return None
    return list(session.scalars(select(Driver.id).where(Driver.managed_by == user.id)))
