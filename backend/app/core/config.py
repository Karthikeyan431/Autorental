"""Configuration from the environment (hard constraint 8: no secrets in source).

Values come from environment variables, falling back to backend/.env (written by
scripts/db-setup.ps1 for development). backend/.env.example documents every field.
"""

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

_PLACEHOLDER_MARKERS = ("change-me", "changeme", "placeholder", "example", "dev-only")
_MIN_SECRET_KEY_LENGTH = 32
_ENCRYPTION_KEY_BYTES = 32


class UnsafeConfigError(RuntimeError):
    """The configuration is not safe for APP_ENV=production. The app refuses to start."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        env_ignore_empty=True,  # "DOCUMENTS_DIR=" means "use the default", never the cwd
    )

    APP_ENV: Literal["development", "test", "production"] = "development"

    # Runtime connection as app_user, and the migration connection as app_owner.
    DATABASE_URL: str
    MIGRATION_DATABASE_URL: str
    # Used only by the test suite (database names must end in _test).
    TEST_DATABASE_URL: str | None = None
    TEST_MIGRATION_DATABASE_URL: str | None = None

    # Secrets. Empty is tolerated outside production only.
    SECRET_KEY: SecretStr = SecretStr("")
    FIELD_ENCRYPTION_KEY: SecretStr = SecretStr("")  # base64 of 32 bytes (AES-256-GCM)
    FIELD_ENCRYPTION_KEY_ID: str = "f1"  # stored with each encrypted value, for rotation
    FILE_ENCRYPTION_KEYS: SecretStr = SecretStr("")  # "key_id:base64,key_id:base64"
    ACTIVE_FILE_KEY_ID: str = ""

    DOCUMENTS_DIR: Path = REPO_DIR / "data" / "files"
    UIDAI_CERT_PATH: Path | None = None

    # Feature flags. Both default to off (N13; hard constraint 6).
    AADHAAR_QR_INAPP_ENABLED: bool = False
    DEMO_VERIFIER_ENABLED: bool = False

    # Sign-in throttle per IP address: this many failures within the window gives 429.
    LOGIN_IP_MAX_FAILURES: int = Field(default=20, ge=1)
    LOGIN_IP_WINDOW_MINUTES: int = Field(default=15, ge=1)

    # Development seed only: the password for the fake owner and staff. Never committed.
    SEED_DEV_PASSWORD: SecretStr = SecretStr("")

    CORS_ORIGIN: str = ""
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == _ENCRYPTION_KEY_BYTES
    except (binascii.Error, ValueError):
        return False


def check_production_safety(settings: Settings) -> None:
    """Raise UnsafeConfigError naming every unsafe setting (never their values)."""
    if not settings.is_production:
        return
    problems: list[str] = []

    if settings.DEMO_VERIFIER_ENABLED:
        problems.append("DEMO_VERIFIER_ENABLED must be false in production")

    secret_key = settings.SECRET_KEY.get_secret_value()
    if len(secret_key) < _MIN_SECRET_KEY_LENGTH or _is_placeholder(secret_key):
        problems.append(f"SECRET_KEY must be a random value of {_MIN_SECRET_KEY_LENGTH}+ chars")

    field_key = settings.FIELD_ENCRYPTION_KEY.get_secret_value()
    if _is_placeholder(field_key) or not _is_key(field_key):
        problems.append("FIELD_ENCRYPTION_KEY must be base64 of 32 random bytes")
    if not settings.FIELD_ENCRYPTION_KEY_ID.strip():
        problems.append("FIELD_ENCRYPTION_KEY_ID must not be empty")

    file_keys: dict[str, str] = {}
    for item in filter(None, settings.FILE_ENCRYPTION_KEYS.get_secret_value().split(",")):
        key_id, _, key = item.partition(":")
        file_keys[key_id.strip()] = key.strip()
    if not file_keys or any(_is_placeholder(k) or not _is_key(k) for k in file_keys.values()):
        problems.append("FILE_ENCRYPTION_KEYS must be key_id:base64-of-32-bytes entries")
    if settings.ACTIVE_FILE_KEY_ID not in file_keys:
        problems.append("ACTIVE_FILE_KEY_ID must name one of FILE_ENCRYPTION_KEYS")

    if problems:
        raise UnsafeConfigError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required values come from the environment or backend/.env
