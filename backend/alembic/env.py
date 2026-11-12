"""Alembic environment. Migrations always run as app_owner (MIGRATION_DATABASE_URL)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

import app.models  # noqa: F401  # every model, so Base.metadata is complete
from app.core.config import get_settings
from app.core.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # Tests pass the URL explicitly; otherwise use the environment / backend/.env.
    return config.get_main_option("sqlalchemy.url") or get_settings().MIGRATION_DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url(), poolclass=pool.NullPool)  # one-off connection, nothing pooled
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
