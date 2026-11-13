r"""Auth endpoints. The refresh token travels only in an httpOnly, Secure, SameSite=Strict cookie
scoped to /api/v1/auth; a readable `arms_csrf` cookie is echoed in X-CSRF-Token on refresh.
Both are always Secure, in every environment (phone testing uses https: scripts\dev.ps1 -Lan)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.permissions import CurrentUser, authenticated, public
from app.core.request_context import client_ip, user_agent
from app.core.tokens import REFRESH_TOKEN_TTL
from app.modules.auth import service
from app.modules.auth.schemas import (
    ChallengeIn,
    ChallengeOut,
    ChangePasswordIn,
    EnrolledOut,
    LoginIn,
    SignedIn,
    TotpConfirmIn,
    TotpIn,
    TotpSetupOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "arms_refresh"
CSRF_COOKIE = "arms_csrf"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_PATH = "/api/v1/auth"

DbSession = Annotated[Session, Depends(get_session)]
Public = Annotated[None, Depends(public())]


def _client(request: Request) -> service.Client:
    return service.Client(ip=client_ip(request), user_agent=user_agent(request))


def _set_cookies(response: Response, result: service.SignInResult) -> None:
    max_age = int(REFRESH_TOKEN_TTL.total_seconds())
    response.set_cookie(
        REFRESH_COOKIE,
        result.refresh_token,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        result.csrf_token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=False,
        samesite="strict",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=True, httponly=True, samesite="strict"
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")


def _signed_in(request: Request, response: Response, result: service.SignInResult) -> SignedIn:
    _set_cookies(response, result)
    return SignedIn(
        access_token=result.access_token, expires_in=result.expires_in, user=result.user
    )


@router.post("/login", response_model=SignedIn | ChallengeOut, response_model_exclude_none=True)
def login(
    body: LoginIn, request: Request, response: Response, session: DbSession, _: Public
) -> SignedIn | ChallengeOut:
    result = service.login(
        session,
        request.app.state.settings,
        login_id=body.login,
        password=body.password,
        client=_client(request),
    )
    if isinstance(result, service.ChallengeResult):
        return ChallengeOut(status=result.status, challenge_token=result.challenge_token)  # type: ignore[arg-type]
    return _signed_in(request, response, result)


@router.post("/totp", response_model=SignedIn)
def totp(
    body: TotpIn, request: Request, response: Response, session: DbSession, _: Public
) -> SignedIn:
    result = service.complete_totp(
        session,
        request.app.state.settings,
        challenge_token=body.challenge_token,
        code=body.code,
        recovery_code=body.recovery_code,
        client=_client(request),
    )
    return _signed_in(request, response, result)


@router.post("/totp/setup", response_model=TotpSetupOut)
def totp_setup(body: ChallengeIn, request: Request, session: DbSession, _: Public) -> TotpSetupOut:
    secret, uri, svg = service.totp_setup(
        session, request.app.state.settings, challenge_token=body.challenge_token
    )
    return TotpSetupOut(secret=secret, otpauth_uri=uri, qr_svg=svg)


@router.post("/totp/confirm", response_model=EnrolledOut)
def totp_confirm(
    body: TotpConfirmIn, request: Request, response: Response, session: DbSession, _: Public
) -> EnrolledOut:
    result, codes = service.totp_confirm(
        session,
        request.app.state.settings,
        challenge_token=body.challenge_token,
        code=body.code,
        client=_client(request),
    )
    _set_cookies(response, result)
    return EnrolledOut(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=result.user,
        recovery_codes=codes,
    )


@router.post("/refresh", response_model=SignedIn)
def refresh(request: Request, response: Response, session: DbSession, _: Public) -> SignedIn:
    result = service.refresh_session(
        session,
        request.app.state.settings,
        refresh_token=request.cookies.get(REFRESH_COOKIE),
        csrf_cookie=request.cookies.get(CSRF_COOKIE),
        csrf_header=request.headers.get(CSRF_HEADER),
        client=_client(request),
    )
    return _signed_in(request, response, result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    session: DbSession,
    user: Annotated[CurrentUser, Depends(authenticated(allow_pending_password_change=True))],
) -> Response:
    service.logout(session, user, _client(request))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(response)
    return response


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    request: Request,
    session: DbSession,
    user: Annotated[CurrentUser, Depends(authenticated(allow_pending_password_change=True))],
) -> Response:
    service.change_password(
        session,
        user,
        current_password=body.current_password,
        new_password=body.new_password,
        client=_client(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
