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
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import make_engine
from app.main import create_app
from tests.helpers import random_key_b64

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    base = Settings()  # values come from backend/.env
    if not base.TEST_DATABASE_URL or not base.TEST_MIGRATION_DATABASE_URL:
        pytest.exit("TEST_DATABASE_URL is not set. Run scripts\\db-setup.ps1 first.", returncode=2)
    for url in (base.TEST_DATABASE_URL, base.TEST_MIGRATION_DATABASE_URL):
        database = make_url(url).database or ""
        if not database.endswith("_test"):
            pytest.exit(f"Refusing to run tests against database {database!r}.", returncode=2)
    # Documents go to a throwaway folder, encrypted with keys made for this run, so the tests
    # never write into the developer's data folder and never depend on its keys.
    return base.model_copy(
        update={
            "APP_ENV": "test",
            "DATABASE_URL": base.TEST_DATABASE_URL,
            "MIGRATION_DATABASE_URL": base.TEST_MIGRATION_DATABASE_URL,
            "DOCUMENTS_DIR": tmp_path_factory.mktemp("documents"),
            "FILE_ENCRYPTION_KEYS": SecretStr(f"t1:{random_key_b64()}"),
            "ACTIVE_FILE_KEY_ID": "t1",
            "LOOKUP_HMAC_KEY": SecretStr(random_key_b64()),
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


TABLES_SQL = text(
    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
    "AND tablename <> 'alembic_version' ORDER BY tablename"
)


def _truncate(engine: Engine) -> None:
    """Empty every table (each new week's tables included) and restart owned sequences."""
    with engine.begin() as connection:
        tables = [row[0] for row in connection.execute(TABLES_SQL)]
        quoted = ", ".join(f'"{name}"' for name in tables)
        connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture
def clean_db(owner_engine: Engine) -> Iterator[None]:
    _truncate(owner_engine)
    yield
    _truncate(owner_engine)
