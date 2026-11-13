"""Database engine, declarative base and the session-per-request dependency.

The app connects as app_user. A write endpoint runs in exactly one transaction: the
dependency commits after the handler returns and rolls back if it raises. Audit entries are
written with the same session, so they commit or roll back together with the change.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, Engine, MetaData, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """For tables that can be updated. Insert-only tables use CreatedAtMixin only."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def make_engine(url: str, **kwargs: Any) -> Engine:
    options: dict[str, Any] = {
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": 3, "options": "-c timezone=UTC"},
    }
    options.update(kwargs)
    return create_engine(url, **options)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """One session and one transaction per request.

    Commits when the handler returns, rolls back when it raises, except for an AppError raised
    with `keep_changes=True`, which commits first (see app.core.errors.AppError).
    """
    factory: sessionmaker[Session] = request.app.state.sessionmaker
    with factory() as session:
        session.begin()
        try:
            yield session
        except Exception as exc:
            if getattr(exc, "keep_changes", False) is True:
                session.commit()
            else:
                session.rollback()
            raise
        else:
            session.commit()
