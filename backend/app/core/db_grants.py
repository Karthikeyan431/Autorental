"""Database grants for the runtime role, used by migrations.

* `app_owner` owns the schema and runs migrations.
* `app_user` is the runtime role. Default privileges give it SELECT, INSERT, UPDATE and
  DELETE on every table app_owner creates, and USAGE/SELECT on sequences.
* Insert-only tables additionally have UPDATE, DELETE and TRUNCATE revoked from app_user,
  in the migration that creates them (see docs/data-model.md). A test checks every table
  listed here as soon as it exists.
"""

from collections.abc import Sequence

APP_USER_ROLE = "app_user"

INSERT_ONLY_TABLES: Sequence[str] = (
    "audit_logs",
    "settings_versions",
    "rent_charges",
    "kyc_events",
    "escalation_events",
    "document_access_log",
)

# Constant statements (no interpolation). The role name must match APP_USER_ROLE.
DEFAULT_PRIVILEGES_UP = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_user",
)
DEFAULT_PRIVILEGES_DOWN = (
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
    "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_user",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM app_user",
)


def make_insert_only_sql(table: str) -> str:
    """The statement every migration runs for a new insert-only table."""
    if table not in INSERT_ONLY_TABLES:
        raise ValueError(f"{table} is not registered in INSERT_ONLY_TABLES")
    return f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM {APP_USER_ROLE}"
