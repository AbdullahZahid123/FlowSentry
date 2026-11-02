"""Execution endpoints + recovery request handling (API_SPEC sections 10-11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.core.errors import ApiError
from app.core.pagination import decode_cursor, page_meta
from app.deps import get_db_session, get_membership, require_role
from app.models.models import (
    Execution,
    Incident,
    IncidentExecution,
    Integration,
    RecoveryAction,
    Workflow,
    WorkspaceMember,
)
from app.modules import audit
from app.modules.workflows import _executions_page
from app.schemas.common import RetryRequest

router = APIRouter(prefix="/executions", tags=["executions"])


def _load_execution(db: OrmSession, execution_id: uuid.UUID, workspace_id: uuid.UUID) -> Execution:
    e = db.execute(
        select(Execution).where(
            Execution.id == execution_id, Execution.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if e is None:
        raise ApiError("resource_not_found", "Execution not found.", 404)
    return e


@router.get("")
def list_executions(
    request: Request,
    integration_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    status: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_duration_ms: int | None = Query(default=None, ge=0),
    max_duration_ms: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    return _executions_page(
        db,
        request,
        member.workspace_id,
        limit,
        cursor,
        status=status,
        workflow_id=workflow_id,
        integration_id=integration_id,
        started_after=started_after,
        started_before=started_before,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
    )


@router.get("/{execution_id}")
def get_execution(
    execution_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    e = _load_execution(db, execution_id, member.workspace_id)
    w = db.execute(select(Workflow).where(Workflow.id == e.workflow_id)).scalar_one_or_none()
    integration = db.execute(
        select(Integration).where(Integration.id == w.integration_id)
    ).scalar_one_or_none() if w else None
    incident_links = (
        db.execute(
            select(Incident)
            .join(IncidentExecution, IncidentExecution.incident_id == Incident.id)
            .where(IncidentExecution.execution_id == e.id)
        )
        .scalars()
        .all()
    )
    recovery = (
        db.execute(
            select(RecoveryAction)
            .where(RecoveryAction.execution_id == e.id)
            .order_by(RecoveryAction.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    return {
        "data": {
            "id": str(e.id),
            "external_id": e.external_id,
            "status": e.status,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "finished_at": e.finished_at.isoformat() if e.finished_at else None,
            "duration_ms": e.duration_ms,
            "failed_node": e.failed_node,
            "error_class": e.error_class,
            "error_code": e.error_code,
            "error_message_redacted": e.error_message_redacted,
            "source_url": e.source_url,
            "source_retry_of": e.source_retry_of,
            "mode": e.mode,
            "provider_metadata": e.provider_metadata,
            "first_observed_at": e.first_observed_at.isoformat(),
            "last_observed_at": e.last_observed_at.isoformat(),
            "workflow": (
                {"id": str(w.id), "name": w.name, "external_id": w.external_id, "criticality": w.criticality}
                if w
                else None
            ),
            "integration": (
                {"id": str(integration.id), "name": integration.name, "provider": integration.provider}
                if integration
                else None
            ),
            "incidents": [
                {"id": str(i.id), "title": i.title, "status": i.status, "severity": i.severity}
                for i in incident_links
            ],
            "recovery_actions": [
                {
                    "id": str(r.id),
                    "action_type": r.action_type,
                    "status": r.status,
                    "created_at": r.created_at.isoformat(),
                }
                for r in recovery
            ],
        },
        "meta": {"request_id": None},
    }


@router.get("/{execution_id}/events")
def execution_events(
    execution_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    from app.models.models import InboundEvent

    e = _load_execution(db, execution_id, member.workspace_id)
    workflow = db.get(Workflow, e.workflow_id)
    if e.external_id is None or workflow is None:
        return {"data": [], "meta": {"request_id": None}}
    events = (
        db.execute(
            select(InboundEvent)
            .where(
                InboundEvent.workspace_id == member.workspace_id,
                InboundEvent.integration_id == workflow.integration_id,
                InboundEvent.source_execution_id == e.external_id,
            )
            .order_by(InboundEvent.received_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return {
        "data": [
            {
                "id": str(ev.id),
                "event_type": ev.event_type,
                "source_execution_id": ev.source_execution_id,
                "received_at": ev.received_at.isoformat(),
                "processing_status": ev.processing_status,
                "payload_redacted": ev.payload_redacted,
            }
            for ev in events
        ],
        "meta": {"request_id": None},
    }


# --- recovery -----------------------------------------------------------------


def _request_recovery(
    execution_id: uuid.UUID,
    payload: RetryRequest,
    action_type: str,
    request: Request,
    member: WorkspaceMember,
    db: OrmSession,
) -> dict:
    from app.adapters.n8n.adapter import get_adapter

    e = _load_execution(db, execution_id, member.workspace_id)
    if member.role not in ("owner", "admin", "operator"):
        raise ApiError("permission_denied", "Viewers cannot request recovery.", 403)
    if not payload.acknowledge_side_effect_risk:
        raise ApiError(
            "validation_error",
            "Recovery requests require acknowledge_side_effect_risk=true.",
            422,
        )
    integration = db.execute(
        select(Integration).where(Integration.id == _workflow_integration_id(db, e))
    ).scalar_one_or_none()
    if integration is None:
        raise ApiError("resource_not_found", "The source integration was not found.", 404)

    adapter = get_adapter(integration.provider)
    caps = (integration.capabilities or {}).get("retry_execution", False)
    if adapter is None or not caps:
        # ADR-004: no upstream call is made when the capability is unverified.
        raise ApiError(
            "capability_not_supported",
            "This source does not currently advertise a documented, verified "
            "retry capability. Use a manual resolution from the source system "
            "instead.",
            409,
        )

    existing = db.execute(
        select(RecoveryAction).where(
            RecoveryAction.workspace_id == member.workspace_id,
            RecoveryAction.idempotency_key == payload.idempotency_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.execution_id != e.id or existing.action_type != action_type:
            raise ApiError("idempotency_conflict", "The idempotency key was already used.", 409)
        return {
            "data": {
                "recovery_action_id": str(existing.id),
                "status": existing.status,
                "capability": "retry_execution",
                "message": "The original recovery request is returned (idempotent).",
            },
            "meta": {"request_id": request.state.request_id},
        }

    action = RecoveryAction(
        workspace_id=member.workspace_id,
        execution_id=e.id,
        integration_id=integration.id,
        action_type=action_type,
        status="requested",
        requested_by=member.user_id,
        idempotency_key=payload.idempotency_key,
        capability_snapshot=integration.capabilities or {},
        confirmation={"acknowledge_side_effect_risk": True, "mode": payload.mode, "reason": payload.reason},
        created_at=utcnow(),
    )
    db.add(action)
    db.flush()
    audit.record_audit(
        db,
        action=f"recovery.{action_type}_requested",
        resource_type="recovery_action",
        resource_id=action.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"execution_id": str(e.id)},
    )
    db.commit()
    return {
        "data": {
            "recovery_action_id": str(action.id),
            "status": action.status,
            "capability": "retry_execution",
            "message": "The recovery request was accepted for validation.",
        },
        "meta": {"request_id": request.state.request_id},
    }


def _workflow_integration_id(db: OrmSession, e: Execution) -> uuid.UUID:
    w = db.execute(select(Workflow).where(Workflow.id == e.workflow_id)).scalar_one_or_none()
    if w is None:
        raise ApiError("resource_not_found", "The execution has no workflow.", 404)
    return w.integration_id


@router.post("/{execution_id}/retry", status_code=202)
def retry_execution(
    execution_id: uuid.UUID,
    payload: RetryRequest,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    return _request_recovery(execution_id, payload, "retry", request, member, db)


@router.post("/{execution_id}/replay", status_code=202)
def replay_execution(
    execution_id: uuid.UUID,
    payload: RetryRequest,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    return _request_recovery(execution_id, payload, "replay", request, member, db)


recovery_router = APIRouter(prefix="/recovery", tags=["recovery"])


@recovery_router.get("/{recovery_action_id}")
def get_recovery_action(
    recovery_action_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    r = db.execute(
        select(RecoveryAction).where(
            RecoveryAction.id == recovery_action_id,
            RecoveryAction.workspace_id == member.workspace_id,
        )
    ).scalar_one_or_none()
    if r is None:
        raise ApiError("resource_not_found", "Recovery action not found.", 404)
    return {
        "data": {
            "id": str(r.id),
            "action_type": r.action_type,
            "status": r.status,
            "execution_id": str(r.execution_id) if r.execution_id else None,
            "capability_snapshot": r.capability_snapshot,
            "result_metadata": r.result_metadata,
            "error_code": r.error_code,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "created_at": r.created_at.isoformat(),
        },
        "meta": {"request_id": None},
    }
