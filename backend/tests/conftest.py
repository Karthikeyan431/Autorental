"""Test fixtures.

Tests run against the real PostgreSQL test database (arms_test), never SQLite.
At session start the schema is rebuilt with `alembic downgrade base` then `upgrade head`,
so every run also proves the migrations work in both directions.

* `db`        an app_user session inside a transaction that is rolled back after the test.
* `owner_db`  the same, connected as app_owner (for tamper tests and setup only).
* `clean_db`  for tests that commit (API tests, CLI subprocesses): empties every table before
              and after the test, as app_owner.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import make_engine
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    base = Settings()  # values come from backend/.env
    if not base.TEST_DATABASE_URL or not base.TEST_MIGRATION_DATABASE_URL:
        pytest.exit("TEST_DATABASE_URL is not set. Run scripts\\db-setup.ps1 first.", returncode=2)
    for url in (base.TEST_DATABASE_URL, base.TEST_MIGRATION_DATABASE_URL):
        database = make_url(url).database or ""
        if not database.endswith("_test"):
            pytest.exit(f"Refusing to run tests against database {database!r}.", returncode=2)
    return base.model_copy(
        update={
            "APP_ENV": "test",
            "DATABASE_URL": base.TEST_DATABASE_URL,
            "MIGRATION_DATABASE_URL": base.TEST_MIGRATION_DATABASE_URL,
        }
    )


@pytest.fixture(scope="session")
def migrated_db(test_settings: Settings) -> None:
    cfg = alembic_config(test_settings.MIGRATION_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def app_engine(test_settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = make_engine(test_settings.DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def owner_engine(test_settings: Settings, migrated_db: None) -> Iterator[Engine]:
    engine = make_engine(test_settings.MIGRATION_DATABASE_URL)
    yield engine
    engine.dispose()


def _rolled_back_session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db(app_engine: Engine) -> Iterator[Session]:
    yield from _rolled_back_session(app_engine)


@pytest.fixture
def owner_db(owner_engine: Engine) -> Iterator[Session]:
    yield from _rolled_back_session(owner_engine)


@pytest.fixture
def client(test_settings: Settings, migrated_db: None) -> Iterator[TestClient]:
    app = create_app(test_settings)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


TRUNCATE_SQL = text(
    "TRUNCATE recovery_codes, sessions, user_permissions, login_attempts, audit_logs, "
    "settings_versions, users RESTART IDENTITY CASCADE"
)


def _truncate(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(TRUNCATE_SQL)


@pytest.fixture
def clean_db(owner_engine: Engine) -> Iterator[None]:
    _truncate(owner_engine)
    yield
    _truncate(owner_engine)
