"""First-run command: create the single owner account from terminal prompts.

    python -m app.cli.create_owner          (or scripts\\create-owner.ps1)

There is no default password: the password is typed twice, hidden, and must pass the policy.
The authenticator app (TOTP) is set up at the owner's first sign-in in the browser.
Refuses if an owner already exists. Works in every APP_ENV, including production.
"""

import getpass
import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.core.phone import normalise_mobile
from app.core.security import check_password_policy
from app.modules.users.models import User
from app.modules.users.service import create_owner, owner_exists

Ask = Callable[[str], str]
Say = Callable[[str], None]


class OwnerAlreadyExistsError(RuntimeError):
    """There is already an owner account; there can be only one."""


def _ask_required(ask: Ask, say: Say, prompt: str) -> str:
    while True:
        value = ask(prompt).strip()
        if value:
            return value
        say("This is required.")


def _ask_password(ask_secret: Ask, say: Say) -> str:
    while True:
        first = ask_secret("Password (at least 10 characters, hidden): ")
        second = ask_secret("Type the password again: ")
        if first != second:
            say("The two passwords do not match. Try again.")
            continue
        try:
            check_password_policy(first)
        except AppError as exc:
            say(exc.message)
            continue
        return first


def collect_and_create(session: Session, *, ask: Ask, ask_secret: Ask, say: Say) -> User:
    if owner_exists(session):
        raise OwnerAlreadyExistsError("An owner account already exists.")
    name = _ask_required(ask, say, "Owner name: ")
    mobile = _ask_required(ask, say, "Mobile number (10 digits): ")
    try:
        normalise_mobile(mobile)
    except ValueError as exc:
        raise AppError("INVALID_MOBILE", str(exc), status_code=422) from exc
    email = ask("Email (optional, press Enter to skip): ").strip() or None
    password = _ask_password(ask_secret, say)
    return create_owner(session, name=name, mobile=mobile, email=email, password=password)


def main() -> int:
    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    try:
        with make_sessionmaker(engine)() as session, session.begin():
            user = collect_and_create(session, ask=input, ask_secret=getpass.getpass, say=print)
            user_id = user.id
    except OwnerAlreadyExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except AppError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was created.", file=sys.stderr)
        return 130
    finally:
        engine.dispose()
    print(f"Owner account created (user id {user_id}).")
    print("Sign in at the web app; you will set up your authenticator app at first sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
