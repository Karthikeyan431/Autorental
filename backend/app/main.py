"""FastAPI application factory.

Run in development with:  uvicorn app.main:create_app --factory --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  # register every model before any query runs
from app.core.config import Settings, UnsafeConfigError, check_production_safety, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.request_context import REQUEST_ID_HEADER, RequestIdMiddleware
from app.core.scheduler import start_dev_scheduler
from app.modules.agreements.router import router as agreements_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import CSRF_HEADER
from app.modules.auth.router import router as auth_router
from app.modules.documents.router import router as documents_router
from app.modules.drivers.router import router as drivers_router
from app.modules.health.router import router as health_router
from app.modules.kyc.router import router as kyc_router
from app.modules.kyc.service import count_simulated_current_checks
from app.modules.rent.router import router as rent_router
from app.modules.settings.router import router as settings_router
from app.modules.users.router import router as users_router
from app.modules.vehicles.router import router as vehicles_router
from app.version import __version__

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hard constraint 6: production refuses to start while any current KYC check is
    simulated (made with the demo method). Checked against the database at startup."""
    if app.state.settings.is_production:
        with app.state.sessionmaker() as session:
            simulated = count_simulated_current_checks(session)
        if simulated:
            raise UnsafeConfigError(
                f"Refusing to start: {simulated} current KYC check(s) are simulated (demo). "
                "Reopen or redo them with a real method outside production first."
            )
    scheduler = start_dev_scheduler(app.state.settings, app.state.sessionmaker)
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


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
        lifespan=lifespan,
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
        vehicles_router,
        agreements_router,
        rent_router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    return app
