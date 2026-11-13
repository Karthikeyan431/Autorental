"""Permission codes and the per-route access rule (docs/api.md, docs/security.md).

Every route declares exactly one access rule as a dependency parameter:

    def list_users(user: Annotated[CurrentUser, Depends(require(Permission.USERS_MANAGE))]): ...
    def health(_: Annotated[None, Depends(public())]): ...
    def settings(user: Annotated[CurrentUser, Depends(authenticated())]): ...

A test walks every route and fails if one has no rule. The owner has every permission; staff
have the codes stored in `user_permissions`, which can never include an owner-only code.

Every authenticated request re-checks that the user is active and that the session family has
not been revoked, so deactivation, logout and password resets take effect on the next click.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import AppError


class Permission(StrEnum):
    DRIVERS_CREATE = "drivers.create"
    DRIVERS_EDIT_OWN = "drivers.edit_own"
    DRIVERS_EDIT_ANY = "drivers.edit_any"
    DRIVERS_REASSIGN = "drivers.reassign"
    DRIVERS_RESTRICT = "drivers.restrict"
    KYC_DECIDE = "kyc.decide"
    KYC_REOPEN = "kyc.reopen"
    VEHICLES_MANAGE = "vehicles.manage"
    AGREEMENTS_MANAGE = "agreements.manage"
    PAYREQUESTS_SEND = "payrequests.send"
    PAYMENTS_RECORD = "payments.record"
    PAYMENTS_APPROVE = "payments.approve"
    PAYMENTS_REVERSE_DECIDE = "payments.reverse_decide"
    ADJUSTMENTS_REQUEST = "adjustments.request"
    ADJUSTMENTS_DECIDE = "adjustments.decide"
    STATEMENTS_UPLOAD = "statements.upload"
    ADVANCE_DECIDE = "advance.decide"
    ESCALATIONS_RAISE = "escalations.raise"
    ESCALATIONS_WORK = "escalations.work"
    REPORTS_ALL = "reports.all"
    SETTINGS_MANAGE = "settings.manage"
    USERS_MANAGE = "users.manage"
    AUDIT_VIEW = "audit.view"


# Never grantable to staff (requirements §3, D9).
OWNER_ONLY: frozenset[Permission] = frozenset(
    {
        Permission.DRIVERS_REASSIGN,
        Permission.KYC_REOPEN,
        Permission.PAYMENTS_APPROVE,
        Permission.PAYMENTS_REVERSE_DECIDE,
        Permission.ADJUSTMENTS_DECIDE,
        Permission.ADVANCE_DECIDE,
        Permission.ESCALATIONS_RAISE,
        Permission.SETTINGS_MANAGE,
        Permission.USERS_MANAGE,
        Permission.AUDIT_VIEW,
    }
)
GRANTABLE: frozenset[Permission] = frozenset(Permission) - OWNER_ONLY

# What a new staff account starts with (requirements §3; N1, N2, D9).
STAFF_DEFAULTS: frozenset[Permission] = frozenset(
    {
        Permission.DRIVERS_CREATE,
        Permission.DRIVERS_EDIT_OWN,
        Permission.KYC_DECIDE,
        Permission.VEHICLES_MANAGE,
        Permission.AGREEMENTS_MANAGE,
        Permission.PAYREQUESTS_SEND,
        Permission.PAYMENTS_RECORD,
        Permission.ADJUSTMENTS_REQUEST,
        Permission.ESCALATIONS_WORK,
    }
)
# Off by default but the owner may switch them on: drivers.edit_any, drivers.restrict,
# statements.upload, reports.all.

PERMISSION_LABELS: dict[Permission, str] = {
    Permission.DRIVERS_CREATE: "Register drivers",
    Permission.DRIVERS_EDIT_OWN: "Edit the drivers they manage",
    Permission.DRIVERS_EDIT_ANY: "Edit any driver",
    Permission.DRIVERS_REASSIGN: "Change a driver's managing staff member",
    Permission.DRIVERS_RESTRICT: "Suspend or reactivate drivers; place or lift restrictions",
    Permission.KYC_DECIDE: "Approve or reject identity and licence checks",
    Permission.KYC_REOPEN: "Reopen a verification",
    Permission.VEHICLES_MANAGE: "Register autos, papers and maintenance",
    Permission.AGREEMENTS_MANAGE: "Create, activate and end agreements",
    Permission.PAYREQUESTS_SEND: "Generate and send pay requests",
    Permission.PAYMENTS_RECORD: "Record payments and confirm days",
    Permission.PAYMENTS_APPROVE: "Approve or reject payments",
    Permission.PAYMENTS_REVERSE_DECIDE: "Decide payment reversals",
    Permission.ADJUSTMENTS_REQUEST: "Request a charge adjustment or reversal",
    Permission.ADJUSTMENTS_DECIDE: "Decide charge adjustments",
    Permission.STATEMENTS_UPLOAD: "Upload bank statements and confirm matches",
    Permission.ADVANCE_DECIDE: "Decide advance adjustments",
    Permission.ESCALATIONS_RAISE: "Raise or close escalations",
    Permission.ESCALATIONS_WORK: "Work escalations for their drivers",
    Permission.REPORTS_ALL: "Business-wide money figures and reports",
    Permission.SETTINGS_MANAGE: "Change business settings",
    Permission.USERS_MANAGE: "Manage staff and permissions",
    Permission.AUDIT_VIEW: "View the audit log",
}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    role: str
    must_change_password: bool
    permissions: frozenset[str]
    family_id: str

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def has(self, permission: Permission) -> bool:
        return permission.value in self.permissions


def effective_permissions(role: str, granted: Iterable[str]) -> frozenset[str]:
    if role == "owner":
        return frozenset(p.value for p in Permission)
    return frozenset(granted) & frozenset(p.value for p in GRANTABLE)


def unauthenticated() -> AppError:
    return AppError("UNAUTHENTICATED", "Please sign in.", status_code=401)


AccessKind = Literal["public", "authenticated", "permission"]


@dataclass(frozen=True)
class AccessRule:
    """A route's declared access. Instances are FastAPI dependencies."""

    kind: AccessKind
    permission: Permission | None = None
    allow_pending_password_change: bool = False

    def __call__(
        self, request: Request, session: Annotated[Session, Depends(get_session)]
    ) -> CurrentUser | None:
        if self.kind == "public":
            return None
        # Imported here: the users module imports the permission codes from this module.
        from app.modules.auth.service import authenticate_request

        user = authenticate_request(session, request)
        if user.must_change_password and not self.allow_pending_password_change:
            raise AppError(
                "PASSWORD_CHANGE_REQUIRED",
                "Change your password to continue.",
                status_code=403,
            )
        if self.permission is not None and not user.has(self.permission):
            raise AppError("FORBIDDEN", "You do not have permission to do this.", status_code=403)
        return user


def public() -> AccessRule:
    return AccessRule("public")


def authenticated(*, allow_pending_password_change: bool = False) -> AccessRule:
    return AccessRule("authenticated", allow_pending_password_change=allow_pending_password_change)


def require(permission: Permission) -> AccessRule:
    return AccessRule("permission", permission=permission)


def _walk(dependant: Dependant) -> Iterable[AccessRule]:
    for dependency in dependant.dependencies:
        if isinstance(dependency.call, AccessRule):
            yield dependency.call
        yield from _walk(dependency)


@dataclass(frozen=True)
class RouteAccess:
    path: str
    methods: frozenset[str]
    rules: list[AccessRule]


def api_route_access(app: FastAPI) -> list[RouteAccess]:
    """Every API route with its full path and the access rules found in its effective
    dependencies (FastAPI 0.162 nests included routers, so app.routes is not flat)."""
    result: list[RouteAccess] = []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute):
            continue
        dependant: Dependant = getattr(context, "dependant", context.original_route.dependant)
        result.append(
            RouteAccess(
                path=context.path or "",
                methods=frozenset(context.methods or ()),
                rules=list(_walk(dependant)),
            )
        )
    return result
