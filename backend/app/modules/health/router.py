"""GET /api/v1/health: public; reports API and database status (docs/api.md)."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.permissions import public
from app.version import __version__

router = APIRouter(tags=["health"])
_log = logging.getLogger("arms.health")


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unavailable"]
    version: str


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(request: Request, _: Annotated[None, Depends(public())]) -> JSONResponse:
    engine: Engine = request.app.state.engine
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        _log.warning("health check: database unavailable")
        body = HealthOut(status="degraded", db="unavailable", version=__version__)
        return JSONResponse(status_code=503, content=body.model_dump())
    body = HealthOut(status="ok", db="ok", version=__version__)
    return JSONResponse(status_code=200, content=body.model_dump())
