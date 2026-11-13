"""Staff management endpoints (owner only: `users.manage`)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import (
    GRANTABLE,
    PERMISSION_LABELS,
    STAFF_DEFAULTS,
    CurrentUser,
    Permission,
    require,
)
from app.core.request_context import client_ip
from app.modules.users import service
from app.modules.users.schemas import (
    DeactivateIn,
    PasswordResetOut,
    PermissionCatalogue,
    PermissionInfo,
    PermissionsIn,
    StaffCreate,
    StaffCreated,
    StaffUpdate,
    UserOut,
)

router = APIRouter(tags=["users"])

DbSession = Annotated[Session, Depends(get_session)]
Owner = Annotated[CurrentUser, Depends(require(Permission.USERS_MANAGE))]


@router.get("/users", response_model=Page[UserOut])
def list_users(
    session: DbSession,
    _: Owner,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Literal["owner", "staff"] | None = None,
    is_active: bool | None = None,
) -> Page[UserOut]:
    return service.list_users(session, params, search=search, role=role, is_active=is_active)


@router.post("/users", response_model=StaffCreated, status_code=status.HTTP_201_CREATED)
def create_staff(
    body: StaffCreate, request: Request, session: DbSession, owner: Owner
) -> StaffCreated:
    user, temporary = service.create_staff(
        session,
        actor_id=owner.id,
        name=body.name,
        mobile=body.mobile,
        email=body.email,
        ip=client_ip(request),
    )
    if temporary is None:  # always generated when no password is given
        raise RuntimeError("No temporary password was generated.")
    return StaffCreated(user=service.user_out(session, user), temporary_password=temporary)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, session: DbSession, _: Owner) -> UserOut:
    return service.user_out(session, service.get_user(session, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: StaffUpdate, request: Request, session: DbSession, owner: Owner
) -> UserOut:
    user = service.update_user(
        session, actor_id=owner.id, user_id=user_id, changes=body, ip=client_ip(request)
    )
    return service.user_out(session, user)


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: int, body: DeactivateIn, request: Request, session: DbSession, owner: Owner
) -> UserOut:
    user = service.deactivate_user(
        session, actor_id=owner.id, user_id=user_id, reason=body.reason, ip=client_ip(request)
    )
    return service.user_out(session, user)


@router.post("/users/{user_id}/reactivate", response_model=UserOut)
def reactivate_user(user_id: int, request: Request, session: DbSession, owner: Owner) -> UserOut:
    user = service.reactivate_user(
        session, actor_id=owner.id, user_id=user_id, ip=client_ip(request)
    )
    return service.user_out(session, user)


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetOut)
def reset_password(
    user_id: int, request: Request, session: DbSession, owner: Owner
) -> PasswordResetOut:
    temporary = service.reset_password(
        session, actor_id=owner.id, user_id=user_id, ip=client_ip(request)
    )
    return PasswordResetOut(temporary_password=temporary)


@router.put("/users/{user_id}/permissions", response_model=UserOut)
def set_permissions(
    user_id: int, body: PermissionsIn, request: Request, session: DbSession, owner: Owner
) -> UserOut:
    user = service.set_permissions(
        session,
        actor_id=owner.id,
        user_id=user_id,
        permissions=body.permissions,
        ip=client_ip(request),
    )
    return service.user_out(session, user)


@router.get("/permissions", response_model=PermissionCatalogue)
def permission_catalogue(_: Owner) -> PermissionCatalogue:
    return PermissionCatalogue(
        items=[
            PermissionInfo(
                code=code.value,
                label=PERMISSION_LABELS[code],
                grantable=code in GRANTABLE,
                staff_default=code in STAFF_DEFAULTS,
            )
            for code in Permission
        ]
    )
