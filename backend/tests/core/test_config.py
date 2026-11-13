"""Configuration comes from the environment; production refuses unsafe settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, UnsafeConfigError, check_production_safety
from app.main import create_app
from tests.helpers import make_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_production_refuses_the_demo_verifier() -> None:
    settings = make_settings(APP_ENV="production", DEMO_VERIFIER_ENABLED=True)
    with pytest.raises(UnsafeConfigError, match="DEMO_VERIFIER_ENABLED"):
        create_app(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("SECRET_KEY", ""),
        ("SECRET_KEY", "too-short"),
        ("SECRET_KEY", "change-me-change-me-change-me-change-me-change-me"),
        ("FIELD_ENCRYPTION_KEY", ""),
        ("FIELD_ENCRYPTION_KEY", "bm90LTMyLWJ5dGVz"),
        ("FILE_ENCRYPTION_KEYS", ""),
        ("FILE_ENCRYPTION_KEYS", "k1:not-base64!"),
        ("ACTIVE_FILE_KEY_ID", "missing"),
    ],
)
def test_production_refuses_missing_or_weak_secrets(field: str, value: str) -> None:
    settings = make_settings(APP_ENV="production", **{field: value})
    with pytest.raises(UnsafeConfigError, match=field):
        check_production_safety(settings)


def test_unsafe_config_error_never_contains_secret_values() -> None:
    weak = "change-me-change-me-change-me-change-me-change-me"
    settings = make_settings(APP_ENV="production", SECRET_KEY=weak)
    with pytest.raises(UnsafeConfigError) as caught:
        check_production_safety(settings)
    assert weak not in str(caught.value)


def test_production_with_safe_settings_starts() -> None:
    create_app(make_settings(APP_ENV="production"))


def test_development_allows_the_demo_verifier() -> None:
    create_app(make_settings(APP_ENV="development", DEMO_VERIFIER_ENABLED=True))


def test_flags_default_to_off() -> None:
    settings = make_settings()
    assert settings.AADHAAR_QR_INAPP_ENABLED is False
    assert settings.DEMO_VERIFIER_ENABLED is False


def test_unknown_app_env_is_refused() -> None:
    with pytest.raises(ValidationError):
        make_settings(APP_ENV="staging")


def test_openapi_docs_are_off_in_production() -> None:
    assert create_app(make_settings(APP_ENV="production")).openapi_url is None
    assert create_app(make_settings(APP_ENV="development")).openapi_url is not None


def _example_keys() -> set[str]:
    keys: set[str] = set()
    for line in (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_env_example_lists_every_setting() -> None:
    assert _example_keys() == set(Settings.model_fields)


def test_env_example_contains_no_real_values() -> None:
    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(
            ("SECRET_KEY=", "FIELD_ENCRYPTION_KEY=", "FILE_ENCRYPTION_KEYS=", "SEED_DEV_PASSWORD=")
        ):
            assert line.split("=", 1)[1].strip() in {"", "change-me"}
