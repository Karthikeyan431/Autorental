"""Who may do what with a driver (N1, N2 and the Week 3 decisions D33-D35).

* Every signed-in user can see every driver and the driver photo (N1).
* Editing: the owner; staff with `drivers.edit_any`; staff with `drivers.edit_own` for the
  drivers they manage. Anyone else gets 403 DRIVER_NOT_EDITABLE (they can see the driver).
* KYC (documents, details, consents, decisions, the KYC parts of the timeline and eligibility):
  the owner, the managing staff member, and staff with `drivers.edit_any`. Anyone else gets 404,
  as if the record did not exist (docs/security.md).
* Deciding also needs `kyc.decide` (route rule); reopening needs `kyc.reopen` (owner only).
"""

from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.models import Driver


def not_found() -> AppError:
    return AppError("NOT_FOUND", "Not found.", status_code=404)


def can_edit(user: CurrentUser, driver: Driver) -> bool:
    if user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY):
        return True
    return user.has(Permission.DRIVERS_EDIT_OWN) and driver.managed_by == user.id


def can_see_kyc(user: CurrentUser, driver: Driver) -> bool:
    return user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY) or driver.managed_by == user.id


def sees_all_kyc(user: CurrentUser) -> bool:
    return user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY)


def require_edit(user: CurrentUser, driver: Driver) -> None:
    if not can_edit(user, driver):
        raise AppError(
            "DRIVER_NOT_EDITABLE",
            "Only the staff member who manages this driver, or the owner, can change it.",
            status_code=403,
        )


def require_kyc(user: CurrentUser, driver: Driver) -> None:
    if not can_see_kyc(user, driver):
        raise not_found()


def require_kyc_edit(user: CurrentUser, driver: Driver) -> None:
    """KYC capture (consent, attempts, details, uploads, submit): see KYC and edit the driver."""
    require_kyc(user, driver)
    require_edit(user, driver)
