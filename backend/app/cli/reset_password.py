"""Account recovery: set a new password for a user from the server shell.

    python -m app.cli.reset_password [--reset-totp]      (or scripts\\reset-password.ps1)

Asks which user (mobile number or email), then the new password twice (hidden, normal policy).
It clears the lockout, signs the user out everywhere and forces a password change at the next
sign-in. --reset-totp also clears the owner's 2-step setup, so the next sign-in sets up a new
authenticator app (use it when the phone with the authenticator is lost).

Works in every APP_ENV, including production: it needs shell access to the server, which can
already read the database. The audit entry's actor is "system:cli". Nothing secret or personal
is printed: only the user id, role and the last 4 digits of the mobile number.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

import app.models  # noqa: F401  # register every model so foreign keys resolve
from app.cli.create_owner import Ask, Say, _ask_password
from app.core.config import get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import AppError
from app.modules.users.models import User
from app.modules.users.service import find_user_by_login, recover_account


def collect_and_reset(
    session: Session,
    *,
    login_id: str,
    ask_secret: Ask,
    say: Say,
    reset_totp: bool,
) -> User:
    """Find the user, ask for the new password and apply the recovery (caller commits)."""
    user = find_user_by_login(session, login_id)
    if reset_totp and user.role != "owner":
        # Refuse before asking for a password that would not be used.
        return recover_account(session, user, new_password="", reset_totp=True)
    say(
        f"Resetting the password of user {user.id} ({user.role}, mobile ending {user.mobile[-4:]})."
    )
    if not user.is_active:
        say(
            "Note: this account is deactivated; the owner must reactivate it before it can sign in."
        )
    password = _ask_password(ask_secret, say, name=user.name, mobile=user.mobile)
    return recover_account(session, user, new_password=password, reset_totp=reset_totp)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.reset_password",
        description="Set a new password for a user (account recovery from the server shell).",
    )
    parser.add_argument(
        "--reset-totp",
        action="store_true",
        help="also clear the owner's 2-step sign-in (authenticator app) setup",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine(settings.DATABASE_URL)
    try:
        login_id = input("User's mobile number or email: ").strip()
        with make_sessionmaker(engine)() as session, session.begin():
            user = collect_and_reset(
                session,
                login_id=login_id,
                ask_secret=getpass.getpass,
                say=print,
                reset_totp=args.reset_totp,
            )
            user_id, role = user.id, user.role
    except AppError as exc:
        print(f"{exc.message} Nothing was changed.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was changed.", file=sys.stderr)
        return 130
    finally:
        engine.dispose()

    print(f"Password reset for user {user_id} ({role}). They were signed out everywhere.")
    print("They must choose a new password at their next sign-in.")
    if args.reset_totp:
        print("2-step sign-in was cleared: the next sign-in sets up a new authenticator app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
