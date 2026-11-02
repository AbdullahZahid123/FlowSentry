"""Audit log query endpoints (API_SPECIFICATION.md section 14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.deps import get_db_session, require_role
from app.models.models import WorkspaceMember

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    actor_type: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    member: WorkspaceMember = Depends(require_role("viewer")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    q = (
        select()
        .columns()  # placeholder to keep structure explicit
    )
    from app.models.models import AuditLog

    q = (
        select(AuditLog)
        .where(AuditLog.workspace_id == member.workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if actor_type:
        q = q.where(AuditLog.actor_type == actor_type)
    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    rows = db.execute(q).scalars().all()
    return {
        "data": [
            {
                "id": str(a.id),
                "action": a.action,
                "actor_type": a.actor_type,
                "actor_id": str(a.actor_id) if a.actor_id else None,
                "resource_type": a.resource_type,
                "resource_id": str(a.resource_id) if a.resource_id else None,
                "request_id": a.request_id,
                "metadata": a.metadata,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "meta": {"request_id": request.state.request_id, "next_cursor": None, "has_more": False},
    }
