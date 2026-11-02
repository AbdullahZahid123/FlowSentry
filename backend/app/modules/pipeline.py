"""Post-ingestion pipeline: turn durably accepted inbound events into
executions, incidents, and notifications (PRD 9.5–9.8, ARCH 9.2–9.4).

Guarantees:
- Processing is idempotent: upserts by (integration, external_id), incident
  grouping by fingerprint, notification dedupe by workspace+dedupe_key.
- Failures never re-acknowledge an event: the worker marks the row
  failed/dead_letter, and the unprocessed index allows re-claims.
- Every durable state change is mirrored onto an in-process SSE bus and an
  outbox row so other processes can relay to their own streams.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session as OrmSession

from app.adapters.n8n.adapter import get_adapter
from app.core import config
from app.core.db import utcnow, advisory_xact_lock
from app.core.errors import ApiError
from app.core.fingerprint import FingerprintInput, compute_fingerprint
from app.core.sse import bus
from app.models.models import (
    AlertRule,
    AlertRuleChannel,
    Execution,
    Incident,
    IncidentExecution,
    IncidentTimelineEvent,
    InboundEvent,
    Integration,
    MaintenanceWindow,
    Notification,
    NotificationChannel,
    OutboxMessage,
    Workflow,
)

logger = logging.getLogger("flowsentry.pipeline")

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_CRITICALITY_TO_SEVERITY = {
    "critical": "critical",
    "high": "high",
    "normal": "medium",
    "low": "low",
}


def emit_event(
    db: OrmSession,
    workspace_id: uuid.UUID,
    event: str,
    data: dict[str, Any],
) -> None:
    """Durable SSE publication: written as an outbox row; stream handlers
    tail the table and republish onto their local bus."""
    db.add(
        OutboxMessage(
            workspace_id=workspace_id,
            aggregate_type="sse_event",
            aggregate_id=uuid.uuid4(),
            message_type="sse.event",
            payload={"event": event, "data": data},
            available_at=utcnow(),
            published_at=utcnow(),  # already durable; rows are a relay buffer
        )
    )


def _maintenance_active(db: OrmSession, workspace_id: uuid.UUID) -> bool:
    now = utcnow()
    window = db.execute(
        select(MaintenanceWindow.id)
        .where(
            MaintenanceWindow.workspace_id == workspace_id,
            MaintenanceWindow.starts_at <= now,
            MaintenanceWindow.ends_at >= now,
        )
        .limit(1)
    ).scalar_one_or_none()
    return window is not None


def _upsert_execution(
    db: OrmSession,
    *,
    workspace_id: uuid.UUID,
    integration_id: uuid.UUID,
    workflow: Workflow,
    external_id: str | None,
    status: str,
    started_at=None,
    finished_at=None,
    duration_ms: int | None = None,
    failed_node: str | None = None,
    error_class: str | None = None,
    error_message_redacted: str | None = None,
    source_url: str | None = None,
    mode: str | None = None,
    provider_metadata: dict[str, Any] | None = None,
) -> tuple[Execution, bool]:
    """Returns (execution, created). Idempotent on (workflow_id, external_id)."""
    execution: Execution | None = None
    if external_id:
        execution = db.execute(
            select(Execution).where(
                Execution.workflow_id == workflow.id, Execution.external_id == external_id
            )
        ).scalar_one_or_none()
    now = utcnow()
    if execution is None:
        execution = Execution(
            workspace_id=workspace_id,
            workflow_id=workflow.id,
            external_id=external_id,
            status=status,
        )
        db.add(execution)
        db.flush()
        created = True
    else:
        created = False
        workflow_id_known = execution.workflow_id == workflow.id
        if not workflow_id_known:  # never cross-tenant (defensive; DB also enforces)
            raise ApiError("resource_not_found", "Execution does not belong to the workflow.", 404)
        execution.status = status

    if started_at is not None:
        execution.started_at = started_at
    execution.finished_at = finished_at if finished_at is not None else execution.finished_at
    if duration_ms is not None:
        execution.duration_ms = duration_ms
    elif execution.started_at and execution.finished_at:
        execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)
    execution.failed_node = failed_node if failed_node is not None else execution.failed_node
    execution.error_class = error_class if error_class is not None else execution.error_class
    execution.error_code = None
    if error_message_redacted is not None:
        execution.error_message_redacted = error_message_redacted
    execution.source_url = source_url if source_url is not None else execution.source_url
    execution.mode = mode if mode is not None else execution.mode
    if provider_metadata:
        execution.provider_metadata = provider_metadata
    execution.last_observed_at = now
    db.add(execution)
    db.flush()
    return execution, created


def classify_incident(
    db: OrmSession,
    *,
    workspace_id: uuid.UUID,
    integration: Integration,
    workflow: Workflow,
    execution: Execution | None,
    error_message: str | None,
    error_class: str | None,
    failed_node: str | None,
) -> Incident:
    """Group a failure under an existing open incident or create a new one."""
    if execution is not None:
        linked = db.execute(select(Incident).join(IncidentExecution,
            IncidentExecution.incident_id == Incident.id).where(
            IncidentExecution.execution_id == execution.id)).scalar_one_or_none()
        if linked is not None:
            return linked
    fingerprint, template, err_class, _node = compute_fingerprint(
        FingerprintInput(
            workspace_id=str(workspace_id),
            integration_id=str(integration.id),
            workflow_external_id=workflow.external_id,
            error_class=error_class,
            failed_node=failed_node,
            error_message=error_message,
        )
    )
    now = utcnow()
    window_start = now - timedelta(seconds=config.settings.grouping_window_seconds)
    advisory_xact_lock(db, f"incident:{integration.id}:{fingerprint}")

    incident = db.execute(
        select(Incident).where(
            Incident.integration_id == integration.id,
            Incident.fingerprint == fingerprint,
            Incident.status.in_(("open", "acknowledged", "investigating", "recovering")),
            Incident.last_seen_at >= window_start,
        )
        .order_by(Incident.last_seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    recoverable_severity = _CRITICALITY_TO_SEVERITY.get(workflow.criticality, "medium")

    if incident is None:
        incident = Incident(
            workspace_id=workspace_id,
            workflow_id=workflow.id,
            integration_id=integration.id,
            fingerprint=fingerprint,
            title=f"{workflow.name} failed ({err_class})",
            summary=template,
            severity=recoverable_severity,
            status="open",
            occurrence_count=0,
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentTimelineEvent(
                workspace_id=workspace_id,
                incident_id=incident.id,
                actor_type="system",
                event_type="incident.created",
                message=f"Incident auto-created from {err_class} failure on {workflow.name}.",
                created_at=now,
            )
        )
    elif now - incident.last_seen_at > timedelta(seconds=config.settings.severity_window_seconds):
        # escalation window elapsed: reflect the workflow criticality again
        if _SEVERITY_RANK[recoverable_severity] > _SEVERITY_RANK[incident.severity]:
            incident.severity = recoverable_severity
            db.add(
                IncidentTimelineEvent(
                    workspace_id=workspace_id,
                    incident_id=incident.id,
                    actor_type="system",
                    event_type="incident.severity_changed",
                    message=f"Severity escalated to {recoverable_severity}.",
                    created_at=now,
                )
            )

    incident.occurrence_count += 1
    incident.last_seen_at = now
    if incident.status == "recovering":
        incident.status = "open"  # recurrence cancels recovery
        db.add(
            IncidentTimelineEvent(
                workspace_id=workspace_id,
                incident_id=incident.id,
                actor_type="system",
                event_type="incident.reopened",
                message="Recurrence observed while incident was recovering.",
                created_at=now,
            )
        )
    db.add(incident)
    db.flush()

    if execution is not None:
        db.add(
            IncidentExecution(
                incident_id=incident.id,
                execution_id=execution.id,
                link_reason="fingerprint",
            )
        )
        db.flush()

    return incident


def process_success(
    db: OrmSession,
    *,
    workspace_id: uuid.UUID,
    integration: Integration,
    workflow: Workflow,
    execution: Execution,
) -> None:
    """Grace recovery: first success transitions active incidents to
    `recovering`; a following success auto-resolves them."""
    assert integration.id is not None and execution.id is not None
    actives = (
        db.execute(
            select(Incident).where(
                Incident.workspace_id == workspace_id,
                Incident.integration_id == integration.id,
                Incident.workflow_id == workflow.id,
                Incident.status.in_(("open", "acknowledged", "investigating", "recovering")),
            )
        )
        .scalars()
        .all()
    )
    for incident in actives:
        if execution.started_at is None or execution.started_at < incident.last_seen_at:
            continue
        if incident.status == "recovering":
            incident.status = "resolved"
            incident.resolved_at = utcnow()
            incident.resolution_note = "Auto-resolved after consecutive successful executions."
            db.add(
                IncidentTimelineEvent(
                    workspace_id=workspace_id,
                    incident_id=incident.id,
                    actor_type="system",
                    event_type="incident.resolved",
                    message="Auto-resolved by the recovery monitor.",
                    created_at=utcnow(),
                )
            )
            emit_event(db, workspace_id, "incident.resolved", _incident_ref(incident))
            evaluate_alert_rules(db, workspace_id=workspace_id, event_type="incident.resolved", incident=incident, workflow=workflow)
        else:
            incident.status = "recovering"
            db.add(
                IncidentTimelineEvent(
                    workspace_id=workspace_id,
                    incident_id=incident.id,
                    actor_type="system",
                    event_type="incident.recovering",
                    message="A successful execution was observed for this workflow.",
                    created_at=utcnow(),
                )
            )
            emit_event(db, workspace_id, "incident.updated", _incident_ref(incident))
        db.add(incident)
    db.flush()


def _incident_ref(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": str(incident.id),
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "occurrence_count": incident.occurrence_count,
    }


def evaluate_alert_rules(
    db: OrmSession,
    *,
    workspace_id: uuid.UUID,
    event_type: str,
    incident: Incident | None = None,
    workflow: Workflow | None = None,
    integration: Integration | None = None,
) -> int:
    """Fan a workspace event out to matching alert rules and queue one
    notification per (rule, channel). Returns the number queued."""
    if _maintenance_active(db, workspace_id):
        return 0

    rules = (
        db.execute(
            select(AlertRule).where(AlertRule.workspace_id == workspace_id, AlertRule.enabled.is_(True))
        )
        .scalars()
        .all()
    )
    now = utcnow()
    queued = 0
    for rule in rules:
        if rule.event_types and event_type not in rule.event_types:
            continue
        event_severity = incident.severity if incident else "medium"
        if rule.severity_minimum:
            if _SEVERITY_RANK.get(event_severity, 0) < _SEVERITY_RANK[rule.severity_minimum]:
                continue
        conditions = rule.conditions or {}
        if "workflow_criticality_in" in conditions:
            if workflow is None or workflow.criticality not in conditions["workflow_criticality_in"]:
                continue
        if "consecutive_failures_gte" in conditions:
            threshold = int(conditions["consecutive_failures_gte"])
            if workflow is None:
                continue
            statuses = db.execute(select(Execution.status).where(Execution.workflow_id == workflow.id)
                .order_by(func.coalesce(Execution.started_at, Execution.first_observed_at).desc(), Execution.id.desc())
                .limit(threshold)).scalars().all()
            if len(statuses) < threshold or any(s != "failed" for s in statuses):
                continue
        failure_rate = conditions.get("failure_rate_gte")
        if failure_rate is not None:
            if workflow is None or not _workflow_failure_rate(db, workflow, float(failure_rate)):
                continue
        if "severity_at_least" in conditions:
            if _SEVERITY_RANK.get(event_severity, 0) < _SEVERITY_RANK[conditions["severity_at_least"]]:
                continue

        cooldown_cutoff = now - timedelta(seconds=rule.cooldown_seconds)
        target = incident.id if incident else (workflow.id if workflow else (integration.id if integration else 'global'))
        target_keys = [f"{rule.id}:{event_type}:{target}:"]
        recent = None
        if rule.cooldown_seconds > 0:
            for key in target_keys:
                recent = db.execute(
                    select(Notification.id)
                    .where(
                        Notification.workspace_id == workspace_id,
                        Notification.alert_rule_id == rule.id,
                        Notification.incident_id == (incident.id if incident else None),
                        Notification.dedupe_key.startswith(key),
                        Notification.created_at >= cooldown_cutoff,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if recent is not None:
                    break
            if recent is not None:
                continue

        if incident is not None:
            subject = f"[FlowSentry] {incident.severity.upper()}: {incident.title}"
            body = (
                f"Incident: {incident.title}\n"
                f"Status: {incident.status} | Occurrences: {incident.occurrence_count}\n"
                f"Last seen: {incident.last_seen_at.isoformat()}\n"
                f"Incident ID: {incident.id}"
            )
        else:
            subject = f"[FlowSentry] {event_type}"
            body = f"Event: {event_type}\nWorkflow: {workflow.name if workflow else '-' }\nConnection: {integration.name if integration else '-'}\nAt: {now.isoformat()}"

        rows = db.execute(
            select(AlertRuleChannel.notification_channel_id).where(AlertRuleChannel.alert_rule_id == rule.id)
        ).all()
        for (channel_id,) in rows:
            occurrence = incident.occurrence_count if incident else int(now.timestamp()) // max(rule.cooldown_seconds, 60)
            dedupe = f"{rule.id}:{event_type}:{target}:{occurrence}:{channel_id}"
            exists = db.execute(
                select(Notification.id).where(
                    Notification.workspace_id == workspace_id,
                    Notification.dedupe_key == dedupe,
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            db.add(
                Notification(
                    workspace_id=workspace_id,
                    incident_id=incident.id if incident else None,
                    alert_rule_id=rule.id,
                    channel_id=channel_id,
                    dedupe_key=dedupe,
                    status="queued",
                    subject=subject,
                    body_redacted=body,
                    attempt_count=0,
                    next_attempt_at=now,
                    created_at=now,
                )
            )
            queued += 1
        if queued:
            emit_event(db, workspace_id, "notification.queued", {"alert_rule_id": str(rule.id), "queued": queued})
    db.flush()
    return queued


def _workflow_failure_rate(db: OrmSession, workflow: Workflow, threshold: float) -> bool:
    from sqlalchemy import func

    since = utcnow() - timedelta(hours=1)
    ok = db.execute(
        select(func.count(Execution.id)).where(
            Execution.workflow_id == workflow.id, func.coalesce(Execution.started_at, Execution.first_observed_at) >= since, Execution.status == "success"
        )
    ).scalar() or 0
    failed = db.execute(
        select(func.count(Execution.id)).where(
            Execution.workflow_id == workflow.id, func.coalesce(Execution.started_at, Execution.first_observed_at) >= since, Execution.status == "failed"
        )
    ).scalar() or 0
    known = ok + failed
    return known > 0 and (failed / known) >= threshold


# --- inbound event processing --------------------------------------------------


def process_inbound_event(db: OrmSession, event: InboundEvent) -> str:
    """Consume one durably-accepted inbound event. Returns the new status."""
    if event.processing_status == "processed":
        return "processed"
    advisory_xact_lock(db, f"integration:{event.integration_id}")
    integration = db.get(Integration, event.integration_id)
    if integration is None or integration.deleted_at is not None:
        event.processing_status = "dead_letter"
        event.last_processing_error = "integration_deleted_or_unknown"
        event.processed_at = utcnow()
        db.add(event)
        db.flush()
        return event.processing_status

    adapter = get_adapter(integration.provider)
    payload = event.payload_redacted or {}
    try:
        workflow_identity, parsed = adapter.parse_error_webhook_payload(payload)
    except Exception as e:  # never let a webhook shape change crash the worker
        event.processing_attempts += 1
        event.last_processing_error = str(e)[:500]
        event.processing_status = "failed"
        db.add(event)
        db.flush()
        return event.processing_status

    workflow = None
    if workflow_identity:
        workflow = db.execute(
            select(Workflow).where(
                Workflow.integration_id == integration.id,
                Workflow.external_id == workflow_identity["external_id"],
                Workflow.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if workflow is None:
            workflow = Workflow(
                workspace_id=integration.workspace_id,
                integration_id=integration.id,
                external_id=workflow_identity["external_id"],
                name=workflow_identity.get("name") or f"Workflow {workflow_identity['external_id']}",
            )
            db.add(workflow)
            db.flush()
            emit_event(
                db,
                integration.workspace_id,
                "workflow.updated",
                {"workflow_id": str(workflow.id), "name": workflow.name},
            )

    if workflow is not None and not workflow.monitoring_enabled:
        event.processing_status = "processed"
        event.processed_at = utcnow()
        db.add(event)
        db.flush()
        return event.processing_status

    event_obj = parsed.get("error")
    err_obj = event_obj if isinstance(event_obj, dict) else None
    error_message = str(event_obj) if not isinstance(event_obj, dict) and event_obj else (
        err_obj.get("message") if err_obj else None
    )
    from app.adapters.n8n.adapter import node_name
    failed_node = node_name(parsed.get("last_node_executed")) or node_name((err_obj or {}).get("node"))
    error_class = err_obj.get("name") if err_obj else None

    execution_external_id = parsed.get("execution_external_id")
    incident: Incident | None = None
    execution: Execution | None = None

    if workflow is not None and execution_external_id:
        execution, created = _upsert_execution(
            db,
            workspace_id=event.workspace_id,
            integration_id=integration.id,
            workflow=workflow,
            external_id=execution_external_id,
            status="failed",
            started_at=_payload_started_at(payload),
            failed_node=failed_node,
            error_class=error_class,
            error_message_redacted=error_message,
            source_url=parsed.get("execution_url"),
            mode=parsed.get("mode"),
            provider_metadata={"source": "ingest"},
        )
        if created:
            emit_event(
                db,
                event.workspace_id,
                "execution.created",
                {"execution_id": str(execution.id), "workflow_id": str(workflow.id), "status": execution.status},
            )
        incident = classify_incident(
            db,
            workspace_id=event.workspace_id,
            integration=integration,
            workflow=workflow,
            execution=execution,
            error_message=error_message,
            error_class=error_class,
            failed_node=failed_node,
        )
        evaluate_alert_rules(
            db,
            workspace_id=event.workspace_id,
            event_type="execution.failed",
            incident=incident,
            workflow=workflow,
        )
    elif workflow is not None:
        # Trigger activation failure or unknown execution shape.
        incident = classify_incident(
            db,
            workspace_id=event.workspace_id,
            integration=integration,
            workflow=workflow,
            execution=None,
            error_message=error_message,
            error_class=error_class,
            failed_node=failed_node,
        )
        evaluate_alert_rules(
            db,
            workspace_id=event.workspace_id,
            event_type="execution.failed",
            incident=incident,
            workflow=workflow,
        )

    if incident is not None and incident.occurrence_count == 1:
        evaluate_alert_rules(db, workspace_id=event.workspace_id, event_type="incident.created",
            incident=incident, workflow=workflow)
    event.processing_status = "processed"
    event.processed_at = utcnow()
    event.processing_attempts += 1
    db.add(event)
    if incident is not None:
        emit_event(db, event.workspace_id, "incident.updated", _incident_ref(incident))
    db.flush()
    return event.processing_status


def _payload_started_at(payload: dict[str, Any]):
    execution = payload.get("execution")
    if isinstance(execution, dict) and execution.get("startedAt") is not None:
        from app.adapters.n8n.adapter import N8nAdapter

        return N8nAdapter()._parse_dt(execution.get("startedAt"))
    return None
