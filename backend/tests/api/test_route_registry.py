"""Every route declares its permission (docs/security.md). Fails when a new route forgets."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.permissions import AccessRule, Permission, api_route_access
from app.main import create_app


@pytest.fixture
def app(test_settings: Settings) -> Iterator[FastAPI]:
    application = create_app(test_settings)
    yield application
    application.state.engine.dispose()


def test_every_route_has_exactly_one_declared_permission(app: FastAPI) -> None:
    routes = api_route_access(app)
    assert len(routes) >= 20, "expected the Week 2 routes"
    missing = [f"{sorted(r.methods)} {r.path}" for r in routes if not r.rules]
    doubled = [f"{sorted(r.methods)} {r.path}" for r in routes if len(r.rules) > 1]
    assert not missing, f"Routes with no declared permission: {missing}"
    assert not doubled, f"Routes with more than one access rule: {doubled}"


def _rule(app: FastAPI, method: str, path: str) -> AccessRule:
    for route in api_route_access(app):
        if route.path == path and method in route.methods:
            (rule,) = route.rules
            return rule
    raise AssertionError(f"{method} {path} not found")


def test_known_routes_declare_the_expected_rule(app: FastAPI) -> None:
    assert _rule(app, "GET", "/api/v1/health").kind == "public"
    assert _rule(app, "POST", "/api/v1/auth/login").kind == "public"
    assert _rule(app, "GET", "/api/v1/settings/current").kind == "authenticated"
    assert _rule(app, "POST", "/api/v1/settings").permission is Permission.SETTINGS_MANAGE
    assert _rule(app, "POST", "/api/v1/users").permission is Permission.USERS_MANAGE
    assert _rule(app, "GET", "/api/v1/audit-logs").permission is Permission.AUDIT_VIEW
    change = _rule(app, "POST", "/api/v1/auth/change-password")
    assert change.kind == "authenticated"
    assert change.allow_pending_password_change is True


def test_a_route_without_a_rule_is_detected(test_settings: Settings) -> None:
    application = create_app(test_settings)

    @application.get("/api/v1/forgot-a-rule")
    def forgot() -> dict[str, str]:
        return {}

    try:
        unprotected = [r.path for r in api_route_access(application) if not r.rules]
        assert unprotected == ["/api/v1/forgot-a-rule"]
    finally:
        application.state.engine.dispose()
