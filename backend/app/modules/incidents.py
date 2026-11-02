"""Incident management endpoints (API_SPECIFICATION.md section 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.core.errors import ApiError
from app.core.pagination import decode_cursor, page_meta
from app.deps import get_db_session, get_membership, require_role
from app.models.models import (
    Execution,
    Incident,
    IncidentComment,
    IncidentExecution,
    IncidentTimelineEvent,
    Integration,
    User,
    Workflow,
    WorkspaceMember,
)
from app.modules import audit
from app.schemas.common import CommentRequest, IncidentUpdate, ResolveRequest

router = APIRouter(prefix="/incidents", tags=["incidents"])

VALID_TRANSITIONS = {
    "open": {"acknowledged", "suppressed", "investigating", "resolved"},
    "acknowledged": {"investigating", "resolved", "suppressed", "recovering"},
    "investigating": {"recovering", "resolved", "open"},
    "recovering": {"investigating", "resolved", "open"},
    "suppressed": {"open", "acknowledged"},
    "resolved": {"open"},  # reopen
}


def _incident_payload(i: Incident, workflow: Workflow | None = None, integration: Integration | None = None) -> dict:
    data = {
        "id": str(i.id),
        "title": i.title,
        "summary": i.summary,
        "severity": i.severity,
        "status": i.status,
        "occurrence_count": i.occurrence_count,
        "fingerprint": i.fingerprint,
        "first_seen_at": i.first_seen_at.isoformat(),
        "last_seen_at": i.last_seen_at.isoformat(),
        "acknowledged_at": i.acknowledged_at.isoformat() if i.acknowledged_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "assigned_to": str(i.assigned_to) if i.assigned_to else None,
        "resolution_note": i.resolution_note,
        "workflow_id": str(i.workflow_id) if i.workflow_id else None,
        "integration_id": str(i.integration_id),
        "created_at": i.created_at.isoformat(),
        "updated_at": i.updated_at.isoformat(),
    }
    if workflow is not None:
        data["workflow"] = {"id": str(workflow.id), "name": workflow.name, "criticality": workflow.criticality}
    if integration is not None:
        data["integration"] = {"id": str(integration.id), "name": integration.name, "provider": integration.provider}
    return data


def _load_incident(db: OrmSession, incident_id: uuid.UUID, workspace_id: uuid.UUID) -> Incident:
    i = db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if i is None:
        raise ApiError("resource_not_found", "Incident not found.", 404)
    return i


def _timeline(
    db: OrmSession,
    incident: Incident,
    *,
    actor_type: str,
    actor_id: uuid.UUID | None,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        IncidentTimelineEvent(
            workspace_id=incident.workspace_id,
            incident_id=incident.id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            message=message,
            metadata=metadata or {},
            created_at=utcnow(),
        )
    )


@router.get("")
def list_incidents(
    request: Request,
    status: str | None = None,
    severity: str | None = None,
    integration_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    cur = decode_cursor(cursor) or {}
    q = (
        select(Incident)
        .where(Incident.workspace_id == member.workspace_id)
        .order_by(Incident.last_seen_at.desc(), Incident.id.desc())
    )
    if status:
        q = q.where(Incident.status == status)
    if severity:
        q = q.where(Incident.severity == severity)
    if integration_id:
        q = q.where(Incident.integration_id == integration_id)
    if workflow_id:
        q = q.where(Incident.workflow_id == workflow_id)
    if search:
        q = q.where(Incident.title.ilike(f"%{search[:100]}%"))
    if cur.get("k"):
        q = q.where(
            tuple_(Incident.last_seen_at, Incident.id) < tuple_(cur.get("s"), uuid.UUID(cur["k"]))
        )
    rows = db.execute(q.limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_values = (
        {"k": str(rows[-1].id), "s": rows[-1].last_seen_at.isoformat()} if has_more and rows else None
    )
    return {
        "data": [_incident_payload(i, db.get(Workflow, i.workflow_id) if i.workflow_id else None, db.get(Integration, i.integration_id)) for i in rows],
        "meta": page_meta(request.state.request_id, next_values, has_more),
    }


@router.get("/{incident_id}")
def get_incident(
    incident_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    workflow = (
        db.execute(select(Workflow).where(Workflow.id == i.workflow_id)).scalar_one_or_none()
        if i.workflow_id
        else None
    )
    integration = db.execute(
        select(Integration).where(Integration.id == i.integration_id)
    ).scalar_one_or_none()
    assignee = (
        db.execute(select(User).where(User.id == i.assigned_to)).scalar_one_or_none()
        if i.assigned_to
        else None
    )
    payload = _incident_payload(i, workflow, integration)
    payload["assigned_user"] = (
        {"id": str(assignee.id), "email": assignee.email, "display_name": assignee.display_name}
        if assignee
        else None
    )
    return {"data": payload, "meta": {"request_id": None}}


@router.patch("/{incident_id}")
def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    changed = []
    previous_severity = i.severity
    if payload.severity is not None and payload.severity != i.severity:
        i.severity = payload.severity
        changed.append(f"severity={payload.severity}")
    if "assigned_to" in payload.model_fields_set:
        if not payload.assigned_to:
            i.assigned_to = None
            changed.append("assigned_to=unassigned")
        else:
            try:
                assignee_id = uuid.UUID(payload.assigned_to)
            except ValueError as exc:
                raise ApiError("validation_error", "Invalid assignee ID.", 422) from exc
            target = db.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == member.workspace_id,
                    WorkspaceMember.user_id == assignee_id,
                )
            ).scalar_one_or_none()
            if target is None:
                raise ApiError("validation_error", "The assignee is not a workspace member.", 422)
            i.assigned_to = assignee_id
            changed.append(f"assigned_to={payload.assigned_to}")
    if payload.status is not None and payload.status != i.status:
        _transition(db, i, payload.status, member)
        changed.append(f"status={payload.status}")
    i.updated_at = utcnow()
    db.add(i)
    if changed:
        _timeline(db, i, actor_type="user", actor_id=member.user_id, event_type="incident.updated", message="Updated " + ", ".join(changed))
    from app.modules.pipeline import emit_event
    emit_event(db, member.workspace_id, "incident.updated", {"incident_id": str(i.id)})
    from app.modules.pipeline import evaluate_alert_rules, _SEVERITY_RANK
    if _SEVERITY_RANK[i.severity] > _SEVERITY_RANK[previous_severity]:
        evaluate_alert_rules(db, workspace_id=i.workspace_id, event_type="incident.escalated", incident=i,
                             workflow=db.get(Workflow, i.workflow_id) if i.workflow_id else None)
    audit.record_audit(
        db,
        action="incident.updated",
        resource_type="incident",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"changes": changed},
    )
    db.commit()
    return {"data": _incident_payload(i), "meta": {"request_id": request.state.request_id}}


def _transition(db: OrmSession, i: Incident, new_status: str, member: WorkspaceMember) -> None:
    if new_status not in VALID_TRANSITIONS.get(i.status, set()):
        raise ApiError(
            "conflict",
            f"Transition {i.status} -> {new_status} is not permitted.",
            409,
        )
    now = utcnow()
    if new_status == "acknowledged":
        i.acknowledged_at = now
    if new_status == "resolved":
        i.resolved_at = now
    if new_status == "open" and i.status == "resolved":
        i.resolved_at = None  # reopen clears resolution
    i.status = new_status
    from app.modules.pipeline import emit_event, evaluate_alert_rules
    emit_event(db, i.workspace_id, "incident.updated", {"incident_id": str(i.id)})
    if new_status == "resolved":
        evaluate_alert_rules(db, workspace_id=i.workspace_id, event_type="incident.resolved", incident=i,
                             workflow=db.get(Workflow, i.workflow_id) if i.workflow_id else None)
    _timeline(
        db,
        i,
        actor_type="user",
        actor_id=member.user_id,
        event_type=f"incident.{new_status}",
        message=f"Status changed to {new_status} by {member.role}.",
    )


@router.post("/{incident_id}/acknowledge")
def acknowledge(
    incident_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    if i.status == "acknowledged":
        return {"data": _incident_payload(i), "meta": {"request_id": request.state.request_id}}
    _transition(db, i, "acknowledged", member)
    i.updated_at = utcnow()
    db.add(i)
    audit.record_audit(
        db,
        action="incident.acknowledged",
        resource_type="incident",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _incident_payload(i), "meta": {"request_id": request.state.request_id}}


@router.post("/{incident_id}/resolve")
def resolve(
    incident_id: uuid.UUID,
    payload: ResolveRequest,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    _transition(db, i, "resolved", member)
    i.resolution_note = payload.resolution_note
    i.updated_at = utcnow()
    db.add(i)
    _timeline(
        db,
        i,
        actor_type="user",
        actor_id=member.user_id,
        event_type="incident.resolved",
        message="Incident resolved." + (f" Note: {payload.resolution_note}" if payload.resolution_note else ""),
    )
    audit.record_audit(
        db,
        action="incident.resolved",
        resource_type="incident",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _incident_payload(i), "meta": {"request_id": request.state.request_id}}


@router.post("/{incident_id}/comments", status_code=201)
def add_comment(
    incident_id: uuid.UUID,
    payload: CommentRequest,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    comment = IncidentComment(
        workspace_id=member.workspace_id,
        incident_id=i.id,
        author_id=member.user_id,
        body=payload.body,
        is_internal=payload.is_internal,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(comment)
    _timeline(
        db,
        i,
        actor_type="user",
        actor_id=member.user_id,
        event_type="incident.commented",
        message=payload.body,
    )
    db.commit()
    return {
        "data": {
            "id": str(comment.id),
            "body": comment.body,
            "is_internal": comment.is_internal,
            "author_id": str(comment.author_id),
            "created_at": comment.created_at.isoformat(),
        },
        "meta": {"request_id": request.state.request_id},
    }


@router.get("/{incident_id}/timeline")
def get_timeline(
    incident_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    cur = decode_cursor(cursor) or {}
    query = select(IncidentTimelineEvent).where(IncidentTimelineEvent.incident_id == i.id)
    if cur.get("k"):
        query = query.where(tuple_(IncidentTimelineEvent.created_at, IncidentTimelineEvent.id) < tuple_(cur["s"], uuid.UUID(cur["k"])))
    rows = db.scalars(query.order_by(IncidentTimelineEvent.created_at.desc(), IncidentTimelineEvent.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_values = {"k":str(rows[-1].id),"s":rows[-1].created_at.isoformat()} if has_more and rows else None
    return {
        "data": [
            {
                "id": str(t.id),
                "event_type": t.event_type,
                "message": t.message,
                "actor_type": t.actor_type,
                "actor_id": str(t.actor_id) if t.actor_id else None,
                "metadata": t.metadata,
                "created_at": t.created_at.isoformat(),
            }
            for t in rows
        ],
        "meta": page_meta(request.state.request_id, next_values, has_more),
    }


@router.get("/{incident_id}/executions")
def incident_executions(
    incident_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_incident(db, incident_id, member.workspace_id)
    cur = decode_cursor(cursor) or {}
    q = (
        select(Execution, IncidentExecution.linked_at, IncidentExecution.link_reason)
        .join(IncidentExecution, IncidentExecution.execution_id == Execution.id)
        .where(IncidentExecution.incident_id == i.id)
        .order_by(IncidentExecution.linked_at.desc(), Execution.id.desc())
    )
    if cur.get("k"):
        q = q.where(tuple_(IncidentExecution.linked_at, Execution.id) < tuple_(cur["s"], uuid.UUID(cur["k"])))
    rows = db.execute(q.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_values = {"k": str(rows[-1][0].id), "s": rows[-1][1].isoformat()} if has_more and rows else None
    return {
        "data": [
            {
                "id": str(e.id),
                "status": e.status,
                "external_id": e.external_id,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "failed_node": e.failed_node,
                "error_message_redacted": e.error_message_redacted,
                "source_url": e.source_url,
                "linked_at": linked.isoformat() if linked else None,
                "link_reason": reason,
            }
            for e, linked, reason in rows
        ],
        "meta": page_meta(request.state.request_id, next_values, has_more),
    }
