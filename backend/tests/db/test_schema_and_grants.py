"""Migrations, extensions and the grants that make insert-only tables insert-only."""

import importlib.util
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db_grants import APP_USER_ROLE, INSERT_ONLY_TABLES
from app.modules.users.models import GRANTABLE_CODES_SQL
from tests.conftest import alembic_config

DOCUMENTED_INSERT_ONLY = {
    "audit_logs",
    "settings_versions",
    "rent_charges",
    "kyc_events",
    "escalation_events",
    "document_access_log",
}


def _has_privilege(session: Session, table: str, privilege: str) -> bool:
    return bool(
        session.scalar(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": APP_USER_ROLE, "table": f"public.{table}", "privilege": privilege},
        )
    )


def _existing_tables(session: Session) -> set[str]:
    rows = session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    return {row[0] for row in rows}


def test_insert_only_registry_matches_the_data_model() -> None:
    assert set(INSERT_ONLY_TABLES) == DOCUMENTED_INSERT_ONLY


def test_week_1_insert_only_tables_exist(db: Session) -> None:
    assert {"audit_logs", "settings_versions"} <= _existing_tables(db)


def test_every_existing_insert_only_table_is_locked_for_app_user(db: Session) -> None:
    existing = _existing_tables(db)
    checked = 0
    for table in INSERT_ONLY_TABLES:
        if table not in existing:
            continue  # created in a later week; this test covers it from then on
        checked += 1
        assert _has_privilege(db, table, "SELECT"), table
        assert _has_privilege(db, table, "INSERT"), table
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not _has_privilege(db, table, privilege), f"{table}: {privilege}"
    assert checked >= 2


def test_ordinary_tables_get_full_app_user_grants(db: Session) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _has_privilege(db, "users", privilege), privilege
    assert not _has_privilege(db, "users", "TRUNCATE")


def test_tables_created_later_by_app_owner_get_grants_automatically(owner_db: Session) -> None:
    owner_db.execute(text("CREATE TABLE zz_grant_probe (id bigint)"))
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _has_privilege(owner_db, "zz_grant_probe", privilege), privilege


def test_app_user_cannot_create_tables(db: Session) -> None:
    with pytest.raises(Exception, match="permission denied"):
        db.execute(text("CREATE TABLE zz_should_fail (id bigint)"))


def test_btree_gist_extension_is_installed(db: Session) -> None:
    assert db.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")) == 1


def test_only_one_owner_account_is_allowed(owner_db: Session) -> None:
    insert = text(
        "INSERT INTO users (name, mobile, password_hash, role) "
        "VALUES (:name, :mobile, 'not-a-real-hash', 'owner')"
    )
    owner_db.execute(text("DELETE FROM users"))
    owner_db.execute(insert, {"name": "Test Owner 001", "mobile": "+919000000001"})
    with pytest.raises(IntegrityError):
        owner_db.execute(insert, {"name": "Test Owner 002", "mobile": "+919000000002"})


def test_downgrade_to_base_then_upgrade_to_head(
    test_settings: Settings, owner_engine: Engine
) -> None:
    cfg = alembic_config(test_settings.MIGRATION_DATABASE_URL)
    owner_engine.dispose()  # no pooled connection may hold locks during DDL

    command.downgrade(cfg, "base")
    with owner_engine.connect() as connection:
        remaining = set(inspect(connection).get_table_names()) - {"alembic_version"}
        assert remaining == set()
        default_acl = connection.scalar(text("SELECT count(*) FROM pg_default_acl"))
        assert default_acl == 0

    command.upgrade(cfg, "head")
    with owner_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
    assert {"users", "settings_versions", "audit_logs"} <= tables


def test_migration_0002_grantable_codes_match_the_code() -> None:
    """The database CHECK on user_permissions is a frozen copy of GRANTABLE; keep them equal."""
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    spec = importlib.util.spec_from_file_location(
        "migration_0002", path / "0002_auth_and_permissions.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.GRANTABLE_CODES_SQL == GRANTABLE_CODES_SQL


def test_week_2_tables_get_ordinary_grants(db: Session) -> None:
    for table in ("user_permissions", "sessions", "recovery_codes", "login_attempts"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db.scalar(
                text("SELECT has_table_privilege('app_user', :t, :p)"),
                {"t": table, "p": privilege},
            ), f"{table} {privilege}"
