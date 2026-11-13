"""Sign-in request and response models. Secrets in requests are never echoed or logged."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.users.schemas import UserOut

Secret = Annotated[str, Field(min_length=1, max_length=256)]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: Annotated[str, Field(min_length=1, max_length=254)]  # mobile or email
    password: Secret


class SignedIn(BaseModel):
    status: Literal["ok"] = "ok"
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # not a secret
    expires_in: int
    user: UserOut


class ChallengeOut(BaseModel):
    status: Literal["totp_required", "totp_setup_required"]
    challenge_token: str


class ChallengeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_token: Secret


class TotpIn(BaseModel):
    """Either a 6-digit code from the authenticator app or one recovery code."""

    model_config = ConfigDict(extra="forbid")

    challenge_token: Secret
    code: Annotated[str, Field(pattern=r"^\d{6}$")] | None = None
    recovery_code: Annotated[str, Field(min_length=8, max_length=32)] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "TotpIn":
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Enter the 6-digit code or a recovery code.")
        return self


class TotpConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_token: Secret
    code: Annotated[str, Field(pattern=r"^\d{6}$")]


class TotpSetupOut(BaseModel):
    secret: str  # for typing into the app by hand
    otpauth_uri: str
    qr_svg: str


class EnrolledOut(SignedIn):
    recovery_codes: list[str]  # shown once


class ChangePasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Secret
    new_password: Secret
