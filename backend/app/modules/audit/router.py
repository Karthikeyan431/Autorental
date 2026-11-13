"""Audit log for the owner (`audit.view`): a minimal newest-first list and chain verification.
Filters beyond these and the Excel export come in Week 8."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog, verify_chain
from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params
from app.core.permissions import CurrentUser, Permission, require
from app.modules.users.models import User

router = APIRouter(prefix="/audit-logs", tags=["audit"])

DbSession = Annotated[Session, Depends(get_session)]
Auditor = Annotated[CurrentUser, Depends(require(Permission.AUDIT_VIEW))]


class AuditEntryOut(BaseModel):
    id: int
    occurred_at: datetime
    actor_id: int | None
    actor_name: str | None
    action: str
    entity_type: str
    entity_id: int | None
    before: Any | None
    after: Any | None
    reason: str | None
    request_id: str | None


class ChainOut(BaseModel):
    ok: bool
    checked: int
    first_bad_id: int | None


@router.get("", response_model=Page[AuditEntryOut])
def list_audit_logs(
    session: DbSession,
    _: Auditor,
    params: Annotated[PageParams, Depends(page_params)],
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_id: int | None = None,
) -> Page[AuditEntryOut]:
    query = select(AuditLog, User.name).outerjoin(User, User.id == AuditLog.actor_id)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(AuditLog.id.desc()).offset(params.offset).limit(params.page_size)
    ).all()
    items = [
        AuditEntryOut(
            id=entry.id,
            occurred_at=entry.occurred_at,
            actor_id=entry.actor_id,
            actor_name=name,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            before=entry.before,
            after=entry.after,
            reason=entry.reason,
            request_id=entry.request_id,
        )
        for entry, name in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/verify", response_model=ChainOut)
def verify_audit_chain(session: DbSession, _: Auditor) -> ChainOut:
    result = verify_chain(session)
    return ChainOut(ok=result.ok, checked=result.checked, first_bad_id=result.first_bad_id)
