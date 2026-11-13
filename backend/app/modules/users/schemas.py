"""Request and response models for staff management."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.permissions import Permission
from app.core.phone import normalise_mobile

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _mobile(value: str) -> str:
    return normalise_mobile(value)


def clean_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if len(cleaned) > 254 or not _EMAIL.fullmatch(cleaned):
        raise ValueError("Enter a valid email address.")
    return cleaned


def _name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Enter a name.")
    return cleaned


Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_name)]
Mobile = Annotated[str, Field(max_length=20), AfterValidator(_mobile)]
Email = Annotated[str | None, AfterValidator(clean_email)]


class UserOut(BaseModel):
    id: int
    name: str
    mobile: str
    email: str | None
    role: Literal["owner", "staff"]
    is_active: bool
    must_change_password: bool
    totp_enabled: bool
    last_login_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime
    permissions: list[str]


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    mobile: Mobile
    email: Email = None


class StaffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    mobile: Mobile | None = None
    email: Email = None  # send null or "" to clear


class StaffCreated(BaseModel):
    user: UserOut
    temporary_password: str  # shown once; never stored or logged


class PasswordResetOut(BaseModel):
    temporary_password: str


class DeactivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=500)] | None = None


class PermissionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: Annotated[list[Permission], Field(max_length=len(Permission))]


class PermissionInfo(BaseModel):
    code: str
    label: str
    grantable: bool
    staff_default: bool


class PermissionCatalogue(BaseModel):
    items: list[PermissionInfo]
