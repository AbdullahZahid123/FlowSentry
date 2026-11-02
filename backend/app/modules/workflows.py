"""Workflow endpoints (API_SPECIFICATION.md section 9)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, tuple_, or_, and_
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.core.errors import ApiError
from app.core.pagination import decode_cursor, page_meta
from app.deps import get_db_session, get_membership
from app.models.models import Execution, Integration, Workflow, WorkflowHealthSnapshot, WorkspaceMember
from app.modules.workflows_health import compute_health
from app.schemas.common import WorkflowUpdate

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _workflow_payload(w: Workflow, integration: Integration | None = None, include_health: bool = False) -> dict:
    data = {
        "id": str(w.id),
        "integration_id": str(w.integration_id),
        "external_id": w.external_id,
        "name": w.name,
        "description": w.description,
        "environment": w.environment,
        "is_active": w.is_active,
        "monitoring_enabled": w.monitoring_enabled,
        "criticality": w.criticality,
        "expected_interval_seconds": w.expected_interval_seconds,
        "last_synced_at": w.last_synced_at.isoformat() if w.last_synced_at else None,
        "created_at": w.created_at.isoformat(),
    }
    if integration is not None:
        data["integration"] = {"id": str(integration.id), "name": integration.name, "provider": integration.provider}
    if include_health:
        snap = None  # filled by the health sub-query when requested
        data["health"] = snap
    return data


def _load_workflow(db: OrmSession, workflow_id: uuid.UUID, workspace_id: uuid.UUID) -> Workflow:
    w = db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.workspace_id == workspace_id,
            Workflow.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if w is None:
        raise ApiError("resource_not_found", "Workflow not found.", 404)
    return w


@router.get("")
def list_workflows(
    request: Request,
    integration_id: uuid.UUID | None = None,
    environment: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    cur = decode_cursor(cursor) or {}
    q = (
        select(Workflow)
        .where(Workflow.workspace_id == member.workspace_id, Workflow.deleted_at.is_(None))
        .order_by(Workflow.created_at, Workflow.id)
    )
    if integration_id:
        q = q.where(Workflow.integration_id == integration_id)
    if environment:
        q = q.where(Workflow.environment == environment)
    if search:
        q = q.where(Workflow.name.ilike(f"%{search[:100]}%"))
    if cur.get("id"):
        last_id = uuid.UUID(cur["id"])
        last_created = cur.get("created_at")
        q = q.where(tuple_(Workflow.created_at, Workflow.id) > tuple_(last_created, last_id))
    rows = db.execute(q.limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_values = (
        {"id": str(rows[-1].id), "created_at": rows[-1].created_at.isoformat()} if has_more and rows else None
    )
    # Read current health in one grouped query rather than relying on whether
    # someone previously opened each workflow's health detail page.
    counts = {row[0]: row[1:] for row in db.execute(select(
        Execution.workflow_id,
        func.count().filter(Execution.status == "success"),
        func.count().filter(Execution.status == "failed"),
        func.max(func.coalesce(Execution.started_at, Execution.first_observed_at)),
    ).where(Execution.workflow_id.in_([w.id for w in rows]),
        func.coalesce(Execution.started_at, Execution.first_observed_at) >= utcnow() - timedelta(hours=24)
    ).group_by(Execution.workflow_id)).all()}
    sources = {i.id: i for i in db.execute(select(Integration).where(
        Integration.id.in_({w.integration_id for w in rows}))).scalars()}
    data = []
    for w in rows:
        successes, failures, last_seen = counts.get(w.id, (0, 0, None))
        rate = successes / (successes + failures) if successes + failures else None
        state = "inactive" if w.is_active is False or not w.monitoring_enabled else (
            "unknown" if rate is None else "critical" if rate < .5 else "degraded" if rate < .8 else "healthy")
        if state == "healthy" and w.expected_interval_seconds and last_seen and (
            utcnow() - last_seen).total_seconds() > 3 * w.expected_interval_seconds:
            state = "unknown"
        item = _workflow_payload(w, sources.get(w.integration_id))
        item["health"] = {"state": state, "score": round(rate * 100, 2) if rate is not None else None}
        data.append(item)
    return {
        "data": data,
        "meta": page_meta(request.state.request_id, next_values, has_more),
    }


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    w = _load_workflow(db, workflow_id, member.workspace_id)
    integration = db.execute(
        select(Integration).where(Integration.id == w.integration_id)
    ).scalar_one_or_none()
    latest = (
        db.execute(
            select(WorkflowHealthSnapshot)
            .where(WorkflowHealthSnapshot.workflow_id == w.id)
            .order_by(WorkflowHealthSnapshot.calculated_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    payload = _workflow_payload(w, integration)
    from app.modules.workflow_logic import build_logic_map
    payload["logic"] = build_logic_map((w.provider_metadata or {}).get("topology"))
    payload["health"] = (
        {
            "state": latest.health_state,
            "score": float(latest.health_score) if latest and latest.health_score is not None else None,
            "signals": latest.signals if latest else None,
            "calculated_at": latest.calculated_at.isoformat() if latest else None,
        }
        if latest
        else {"state": "unknown", "score": None, "signals": None, "calculated_at": None}
    )
    return {"data": payload, "meta": {"request_id": None}}


@router.patch("/{workflow_id}")
def update_workflow(
    workflow_id: uuid.UUID,
    payload: WorkflowUpdate,
    request: Request,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    from app.deps import require_role

    # role gate: operator can tag criticality metadata (admin gates elsewhere)
    if ROLE_RANK(member.role) < ROLE_RANK("operator"):
        raise ApiError("permission_denied", "Your role does not permit this action.", 403)
    w = _load_workflow(db, workflow_id, member.workspace_id)
    if payload.monitoring_enabled is not None:
        w.monitoring_enabled = payload.monitoring_enabled
    if payload.name is not None:
        w.name = payload.name
        w.provider_metadata = {**(w.provider_metadata or {}), "_name_override": True}
    if payload.environment is not None:
        w.environment = payload.environment
        w.provider_metadata = {**(w.provider_metadata or {}), "_environment_override": True}
    if payload.criticality is not None:
        w.criticality = payload.criticality
    if payload.expected_interval_seconds is not None:
        w.expected_interval_seconds = payload.expected_interval_seconds
    elif "expected_interval_seconds" in payload.model_fields_set:
        w.expected_interval_seconds = None
    w.updated_at = utcnow()
    db.add(w)
    from app.modules import audit
    audit.record_audit(db, action="workflow.updated", resource_type="workflow", resource_id=w.id,
        workspace_id=member.workspace_id, actor_id=member.user_id, request_id=request.state.request_id)
    db.commit()
    return {"data": _workflow_payload(w), "meta": {"request_id": request.state.request_id}}


def ROLE_RANK(role: str) -> int:
    return {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}[role]


@router.get("/{workflow_id}/health")
def workflow_health(
    workflow_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    w = _load_workflow(db, workflow_id, member.workspace_id)
    result = compute_health(db, w)
    return {"data": result, "meta": {"request_id": None}}


@router.get("/{workflow_id}/executions")
def workflow_executions(
    workflow_id: uuid.UUID,
    request: Request,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    w = _load_workflow(db, workflow_id, member.workspace_id)
    return _executions_page(db, request, member.workspace_id, limit, cursor, status=status, workflow_id=w.id)


def _executions_page(
    db: OrmSession,
    request: Request,
    workspace_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    *,
    status: str | None = None,
    workflow_id: uuid.UUID | None = None,
    integration_id: uuid.UUID | None = None,
    started_after=None,
    started_before=None,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
) -> dict:
    cur = decode_cursor(cursor) or {}
    q = (
        select(Execution)
        .where(Execution.workspace_id == workspace_id)
        .order_by(Execution.started_at.desc().nullslast(), Execution.id.desc())
    )
    if status:
        q = q.where(Execution.status == status)
    if workflow_id:
        q = q.where(Execution.workflow_id == workflow_id)
    if integration_id:
        wf_ids = select(Workflow.id).where(Workflow.integration_id == integration_id)
        q = q.where(Execution.workflow_id.in_(wf_ids))
    if started_after:
        q = q.where(Execution.started_at >= started_after)
    if started_before:
        q = q.where(Execution.started_at <= started_before)
    if min_duration_ms is not None:
        q = q.where(Execution.duration_ms >= min_duration_ms)
    if max_duration_ms is not None:
        q = q.where(Execution.duration_ms <= max_duration_ms)
    if cur.get("k"):
        last_id = uuid.UUID(cur["k"])
        if cur.get("s") is None:
            q = q.where(Execution.started_at.is_(None), Execution.id < last_id)
        else:
            q = q.where(or_(Execution.started_at.is_(None),
                tuple_(Execution.started_at, Execution.id) < tuple_(cur["s"], last_id)))
    rows = db.execute(q.limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_values = (
        {"k": str(rows[-1].id), "s": rows[-1].started_at.isoformat() if rows[-1].started_at else None}
        if has_more and rows
        else None
    )
    return {
        "data": [
            {
                "id": str(e.id),
                "workflow_id": str(e.workflow_id),
                "workflow": _execution_workflow_ref(db, e.workflow_id),
                "integration": _execution_integration_ref(db, e.workflow_id),
                "external_id": e.external_id,
                "status": e.status,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                "duration_ms": e.duration_ms,
                "failed_node": e.failed_node,
                "error_class": e.error_class,
                "error_message_redacted": e.error_message_redacted,
                "source_url": e.source_url,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ],
        "meta": page_meta(request.state.request_id, next_values, has_more),
    }


def _execution_workflow_ref(db, workflow_id):
    w = db.get(Workflow, workflow_id)
    return {"id": str(w.id), "name": w.name, "criticality": w.criticality} if w else None


def _execution_integration_ref(db, workflow_id):
    w = db.get(Workflow, workflow_id)
    i = db.get(Integration, w.integration_id) if w else None
    return {"id": str(i.id), "name": i.name, "provider": i.provider} if i else None
