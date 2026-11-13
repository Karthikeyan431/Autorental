"""FastAPI application factory.

Run in development with:  uvicorn app.main:create_app --factory --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  # register every model before any query runs
from app.core.config import Settings, check_production_safety, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestIdMiddleware
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import CSRF_HEADER
from app.modules.auth.router import router as auth_router
from app.modules.documents.router import router as documents_router
from app.modules.drivers.router import router as drivers_router
from app.modules.health.router import router as health_router
from app.modules.kyc.router import router as kyc_router
from app.modules.settings.router import router as settings_router
from app.modules.users.router import router as users_router
from app.version import __version__

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Refuse to start with an unsafe production configuration (hard constraints 6 and 8).
    check_production_safety(settings)
    configure_logging(settings.LOG_LEVEL)

    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Auto Rental Management System",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
        docs_url=f"{API_PREFIX}/docs" if docs_enabled else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = make_engine(settings.DATABASE_URL)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)

    register_exception_handlers(app)
    if settings.CORS_ORIGIN:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.CORS_ORIGIN],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=[
                "Content-Type",
                "Authorization",
                REQUEST_ID_HEADER,
                "Idempotency-Key",
                CSRF_HEADER,
            ],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(RequestIdMiddleware)

    # Every route declares its access rule (tests/api/test_route_registry.py).
    for router in (
        health_router,
        auth_router,
        users_router,
        settings_router,
        audit_router,
        drivers_router,
        kyc_router,
        documents_router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    return app
