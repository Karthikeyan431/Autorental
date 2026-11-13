"""Who may do what with a driver (N1, N2; Week 3 decisions D33-D35; Week 4 D45, D46).

* Every signed-in user can see every driver and the driver photo (N1).
* Editing: the owner; staff with `drivers.edit_any`; staff with `drivers.edit_own` for the
  drivers they manage. Anyone else gets 403 DRIVER_NOT_EDITABLE (they can see the driver).
  Masked fields (address, date of birth) only by the owner and the current manager (N17):
  403 FIELD_NOT_EDITABLE.
* Seeing KYC status and masked details: the owner, the managing staff member, and staff with
  `drivers.edit_any`. Anyone else gets 404, as if the record did not exist (docs/security.md).
* From Week 4 (D46): KYC document images, KYC capture (consent, attempts, details, uploads,
  submit) and KYC decisions are for the owner and the **current** manager only. Others who can
  see the KYC get 404 for documents, 403 DRIVER_NOT_EDITABLE for capture and
  403 KYC_DECIDE_NOT_ALLOWED for a decision. Deciding also needs `kyc.decide` (route rule);
  reopening needs `kyc.reopen` (owner only).
* Revealing a masked value (D45): the owner and the current manager; others get 403
  REVEAL_NOT_ALLOWED, even with `drivers.edit_any`.

Every check reads `driver.managed_by` at request time, so a manager change takes effect at once.
"""

from app.core.errors import AppError
from app.core.permissions import CurrentUser, Permission
from app.modules.drivers.models import Driver


def not_found() -> AppError:
    return AppError("NOT_FOUND", "Not found.", status_code=404)


def is_owner_or_manager(user: CurrentUser, driver: Driver) -> bool:
    return user.is_owner or driver.managed_by == user.id


def can_edit(user: CurrentUser, driver: Driver) -> bool:
    if user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY):
        return True
    return user.has(Permission.DRIVERS_EDIT_OWN) and driver.managed_by == user.id


def can_see_kyc(user: CurrentUser, driver: Driver) -> bool:
    return user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY) or driver.managed_by == user.id


def sees_all_kyc(user: CurrentUser) -> bool:
    return user.is_owner or user.has(Permission.DRIVERS_EDIT_ANY)


def can_capture_kyc(user: CurrentUser, driver: Driver) -> bool:
    return is_owner_or_manager(user, driver) and can_edit(user, driver)


def can_decide_kyc(user: CurrentUser, driver: Driver) -> bool:
    return is_owner_or_manager(user, driver) and user.has(Permission.KYC_DECIDE)


def _not_editable() -> AppError:
    return AppError(
        "DRIVER_NOT_EDITABLE",
        "Only the staff member who manages this driver, or the owner, can change it.",
        status_code=403,
    )


def require_edit(user: CurrentUser, driver: Driver) -> None:
    if not can_edit(user, driver):
        raise _not_editable()


def require_masked_edit(user: CurrentUser, driver: Driver) -> None:
    if not is_owner_or_manager(user, driver):
        raise AppError(
            "FIELD_NOT_EDITABLE",
            "Only the owner or the driver's manager can change the address or date of birth.",
            status_code=403,
        )


def require_kyc(user: CurrentUser, driver: Driver) -> None:
    if not can_see_kyc(user, driver):
        raise not_found()


def require_kyc_edit(user: CurrentUser, driver: Driver) -> None:
    """KYC capture (consent, attempts, details, uploads, submit): owner or current manager."""
    require_kyc(user, driver)
    if not can_capture_kyc(user, driver):
        raise _not_editable()


def require_kyc_decide(user: CurrentUser, driver: Driver) -> None:
    require_kyc(user, driver)
    if not is_owner_or_manager(user, driver):
        raise AppError(
            "KYC_DECIDE_NOT_ALLOWED",
            "Only the owner or the driver's manager can decide this check.",
            status_code=403,
        )


def require_reveal(user: CurrentUser, driver: Driver) -> None:
    if not is_owner_or_manager(user, driver):
        raise AppError(
            "REVEAL_NOT_ALLOWED",
            "Only the owner or the driver's manager can see this value.",
            status_code=403,
        )
