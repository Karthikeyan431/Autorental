"""Settings: everyone signed in can read; only the owner creates a new version (rule 3)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import AppError
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, authenticated, require
from app.core.request_context import client_ip
from app.modules.settings.models import SettingsVersion
from app.modules.settings.schemas import (
    SettingsChangeRequest,
    SettingsChanges,
    SettingsVersionOut,
)
from app.modules.settings.service import create_settings_version, get_current_settings
from app.modules.users.models import User

router = APIRouter(prefix="/settings", tags=["settings"])

DbSession = Annotated[Session, Depends(get_session)]
SignedIn = Annotated[CurrentUser, Depends(authenticated())]


def _out(session: Session, version: SettingsVersion) -> SettingsVersionOut:
    out = SettingsVersionOut.model_validate(version)
    if version.created_by is not None:
        out.created_by_name = session.scalar(select(User.name).where(User.id == version.created_by))
    return out


@router.get("/current", response_model=SettingsVersionOut | None)
def current_settings(session: DbSession, _: SignedIn) -> SettingsVersionOut | None:
    """The settings in force now, or null before the owner has saved any."""
    version = get_current_settings(session)
    return _out(session, version) if version is not None else None


@router.get("/versions", response_model=Page[SettingsVersionOut])
def settings_versions(
    session: DbSession, _: SignedIn, params: Annotated[PageParams, Depends(page_params)]
) -> Page[SettingsVersionOut]:
    total = session.scalar(select(func.count()).select_from(SettingsVersion)) or 0
    versions = session.scalars(
        select(SettingsVersion)
        .order_by(SettingsVersion.effective_from.desc(), SettingsVersion.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return Page(
        items=[_out(session, v) for v in versions],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=SettingsVersionOut, status_code=status.HTTP_201_CREATED)
def save_settings(
    body: SettingsChangeRequest,
    request: Request,
    session: DbSession,
    owner: Annotated[CurrentUser, Depends(require(Permission.SETTINGS_MANAGE))],
) -> SettingsVersionOut:
    changes = SettingsChanges.model_validate(
        body.model_dump(exclude_unset=True, exclude={"reason"})
    )
    if not changes.model_fields_set:
        raise AppError("NO_SETTINGS_CHANGED", "Change at least one setting.")
    try:
        version = create_settings_version(
            session, changes, actor_id=owner.id, reason=body.reason, ip=client_ip(request)
        )
    except ValidationError as exc:
        # Only possible for the very first version, which needs the rent due time (D20).
        raise AppError(
            "RENT_DUE_TIME_REQUIRED",
            "Set the rent due time to save the first settings.",
            status_code=422,
        ) from exc
    return _out(session, version)
