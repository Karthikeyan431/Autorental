"""Shared helpers for tests that do not need the real database."""

import base64
import secrets
from typing import Any

from app.core.config import Settings

UNREACHABLE_DB_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


def random_key_b64() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def make_settings(**overrides: Any) -> Settings:
    """Settings built only from arguments: no .env file and safe, random secrets."""
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": UNREACHABLE_DB_URL,
        "MIGRATION_DATABASE_URL": UNREACHABLE_DB_URL,
        "SECRET_KEY": secrets.token_hex(32),
        "FIELD_ENCRYPTION_KEY": random_key_b64(),
        "FILE_ENCRYPTION_KEYS": f"k1:{random_key_b64()}",
        "ACTIVE_FILE_KEY_ID": "k1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)
