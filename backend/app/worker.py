"""Background worker loops (PRD 9.5, ADR-005 worker tables).

Three independently idempotent steps run on one heartbeat:
1. Drains inbound events (durably accepted, never re-acknowledged) into
   executions/incidents/notifications with bounded attempts.
2. Delivers due notifications and records every attempt with backoff.
3. Runs due integration syncs for integrations carrying API credentials.

Each step owns short transactions: commit per item, rollback + error record
on failure. The embedded worker runs as a daemon thread.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, or_

from app.core import config
from app.core.db import get_session_factory, utcnow, advisory_xact_lock
from app.core.security import decrypt_secret
from app.models.models import (
    InboundEvent,
    Integration,
    Notification,
    NotificationAttempt,
    NotificationChannel,
    OutboxMessage,
    SyncCursor,
    Workflow,
)
from app.modules import pipeline
from app.modules.notify_send import send_notification_payload

logger = logging.getLogger("flowsentry.worker")

EVENT_MAX_ATTEMPTS = max(config.settings.worker_max_attempts, 8)


def _mark_outbox_published(db, event_id: uuid.UUID) -> None:
    row = (
        db.execute(
            select(OutboxMessage).where(
                OutboxMessage.aggregate_type == "inbound_event",
                OutboxMessage.aggregate_id == event_id,
                OutboxMessage.message_type == "process_event",
                OutboxMessage.published_at.is_(None),
            )
        )
        .scalars()
        .first()
    )
    if row is not None:
        row.published_at = utcnow()
        db.add(row)



def drain_outbox_once() -> int:
    """Process up to worker_batch_size pending inbound events."""
    factory = get_session_factory()
    db = factory()
    processed = 0
    try:
        rows = db.execute(
            select(InboundEvent.id)
            .where(
                InboundEvent.processing_status.in_(("pending", "failed")),
                InboundEvent.processing_attempts < EVENT_MAX_ATTEMPTS,
            )
            .order_by(InboundEvent.received_at)
            .limit(config.settings.worker_batch_size)
        ).all()
        for (event_id,) in rows:
            try:
                event = db.execute(select(InboundEvent).where(
                    InboundEvent.id == event_id,
                    InboundEvent.processing_status.in_(("pending", "failed"))
                ).with_for_update(skip_locked=True)).scalar_one_or_none()
                if event is None:
                    continue
                pipeline.process_inbound_event(db, event)
                _mark_outbox_published(db, event_id)
                db.commit()
                processed += 1
            except Exception:
                db.rollback()
                logger.exception("event processing failed event_id=%s", event_id)
                try:
                    event = db.get(InboundEvent, event_id)
                    if event is not None:
                        event.processing_attempts += 1
                        event.last_processing_error = "worker_error"
                        event.processing_status = (
                            "dead_letter"
                            if event.processing_attempts >= EVENT_MAX_ATTEMPTS
                            else "failed"
                        )
                        db.add(event)
                        db.commit()
                except Exception:
                    db.rollback()
    finally:
        db.close()
    return processed

def deliver_notifications_once() -> int:
    """Send due notifications; record attempts; apply backoff on failure."""
    factory = get_session_factory()
    db = factory()
    delivered = 0
    try:
        due = (
            db.execute(
                select(Notification.id)
                .where(
                    Notification.status.in_(("queued", "failed", "sending")),
                    Notification.next_attempt_at <= utcnow(),
                )
                .order_by(Notification.next_attempt_at)
                .limit(config.settings.worker_batch_size)
            )
            .scalars()
            .all()
        )
        import json

        for notification_id in due:
            try:
                n = db.execute(select(Notification).where(
                    Notification.id == notification_id,
                    Notification.status.in_(("queued", "failed", "sending")),
                    Notification.next_attempt_at <= utcnow(),
                ).with_for_update(skip_locked=True)).scalar_one_or_none()
                if n is None:
                    continue
                for stale in db.execute(select(NotificationAttempt).where(
                    NotificationAttempt.notification_id == n.id,
                    NotificationAttempt.status == "started",
                )).scalars():
                    stale.status = "failed"
                    stale.error_code = "delivery_lease_expired"
                    stale.finished_at = utcnow()
                if n.attempt_count >= config.settings.notification_max_attempts:
                    n.status = "failed"
                    n.last_error = "delivery_attempts_exhausted"
                    n.next_attempt_at = None
                    db.commit()
                    continue
                channel = db.get(NotificationChannel, n.channel_id)
                if channel is None or not channel.enabled:
                    n.status = "canceled"
                    n.last_error = "channel_disabled_or_deleted"
                    db.add(n)
                    db.commit()
                    continue

                n.status = "sending"
                n.attempt_count += 1
                n.next_attempt_at = utcnow() + timedelta(seconds=max(
                    config.settings.worker_job_timeout_seconds,
                    config.settings.http_outbound_timeout_seconds + 30))
                db.add(n)

                config_map: dict[str, Any] = {}
                if channel.configuration_ciphertext:
                    try:
                        config_map = json.loads(decrypt_secret(channel.configuration_ciphertext))
                    except Exception as e:
                        logger.warning("channel config decrypt failed: %s", e)

                attempt_number = n.attempt_count
                attempt = NotificationAttempt(
                    notification_id=n.id,
                    attempt_number=attempt_number,
                    status="started",
                    started_at=utcnow(),
                )
                db.add(attempt)
                db.commit()

                ok, err = send_notification_payload(
                    channel.channel_type,
                    config_map,
                    n.subject or "[FlowSentry] notification",
                    n.body_redacted,
                )
                attempt.status = "succeeded" if ok else "failed"
                if not ok:
                    attempt.error_code = err
                    attempt.error_message = err
                attempt.finished_at = utcnow()
                db.add(attempt)

                n.attempt_count = attempt_number
                now = utcnow()
                if ok:
                    n.status = "delivered"
                    n.delivered_at = now
                    n.last_error = None
                    n.next_attempt_at = None
                    delivered += 1
                else:
                    n.status = "failed"
                    n.last_error = err
                    max_attempts = config.settings.notification_max_attempts
                    if attempt_number >= max_attempts:
                        n.next_attempt_at = None
                    else:
                        delays = config.settings.notification_backoff_seconds or [60]
                        delay = delays[min(attempt_number - 1, len(delays) - 1)]
                        n.next_attempt_at = now + timedelta(seconds=delay)
                db.add(n)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("notification delivery failed notification_id=%s", n.id)
    except Exception:
        db.rollback()
        logger.exception("notification delivery loop crashed")
    finally:
        db.close()
    return delivered

def sync_integrations_once() -> int:
    """Run due sync cursors; each cursor runs in its own short session."""
    factory = get_session_factory()
    ran = 0
    try:
        db = factory()
        try:
            due_ids = [
                row[0]
                for row in db.execute(
                    select(SyncCursor.id)
                    .where(SyncCursor.next_poll_at <= utcnow())
                    .order_by(SyncCursor.next_poll_at)
                    .limit(config.settings.worker_batch_size)
                ).all()
            ]
        finally:
            db.close()
        for cursor_id in due_ids:
            if _run_sync_cursor(factory, cursor_id):
                ran += 1
    except Exception:
        logger.exception("sync loop failed")
    return ran


def _run_sync_cursor(factory, cursor_id: uuid.UUID) -> int:
    from app.adapters.n8n.adapter import get_adapter

    db = factory()
    now = utcnow()
    try:
        cursor = db.execute(select(SyncCursor).where(
            SyncCursor.id == cursor_id,
            or_(SyncCursor.lease_expires_at.is_(None), SyncCursor.lease_expires_at < now)
        ).with_for_update(skip_locked=True)).scalar_one_or_none()
        if cursor is None:
            return 0
        integration = db.get(Integration, cursor.integration_id)
        if integration is None or integration.deleted_at is not None:
            cursor.next_poll_at = now + timedelta(seconds=config.settings.default_poll_interval_seconds)
            cursor.last_error = "integration_missing_or_deleted"
            db.add(cursor)
            db.commit()
            return 0
        if not integration.enabled or not integration.base_url or not integration.credential_ciphertext:
            cursor.next_poll_at = now + timedelta(minutes=15)
            db.add(cursor)
            db.commit()
            return 0

        cursor.last_started_at = now
        cursor.lease_owner = uuid.uuid4().hex
        cursor.lease_expires_at = now + timedelta(seconds=config.settings.worker_job_timeout_seconds)
        db.add(cursor)
        db.commit()

        adapter = get_adapter(integration.provider)
        if adapter is None:
            raise RuntimeError("adapter_not_found")
        credential = decrypt_secret(integration.credential_ciphertext)
        next_poll = now + timedelta(seconds=integration.poll_interval_seconds)
        page = (
            adapter.list_workflows(
                integration.base_url, credential, cursor.cursor_value, config.settings.poll_page_size
            )
            if cursor.resource_type == "workflows"
            else adapter.list_executions(
                integration.base_url, credential, cursor.cursor_value, config.settings.poll_page_size
            )
        )
        advisory_xact_lock(db, f"integration:{integration.id}")
        _apply_sync_page(db, integration, cursor, page, now)

        cursor = db.get(SyncCursor, cursor_id)
        integration = db.get(Integration, integration.id)
        integration.last_successful_check_at = now
        cursor.cursor_value = page.next_cursor
        cursor.watermark_at = now
        cursor.last_success_at = now
        cursor.last_error = None
        cursor.next_poll_at = now if page.next_cursor else next_poll
        cursor.lease_owner = None
        cursor.lease_expires_at = None
        cursor.updated_at = now
        db.add(cursor)
        db.flush()
        other_error = db.scalar(select(SyncCursor.id).where(
            SyncCursor.integration_id == integration.id,
            SyncCursor.last_error.isnot(None)).limit(1))
        integration.status = "degraded" if other_error else "healthy"
        if not other_error:
            integration.last_error_code = None
            integration.last_error_at = None
        db.add(integration)
        db.commit()
        return 1
    except Exception as e:
        db.rollback()
        logger.warning("sync cursor %s failed: %s", cursor_id, e)
        try:
            cursor = db.get(SyncCursor, cursor_id)
            if cursor is not None:
                cursor.last_error = str(e)[:500]
                cursor.lease_owner = None
                cursor.lease_expires_at = None
                cursor.next_poll_at = now + timedelta(minutes=5)
                db.add(cursor)
                failed_integration = db.get(Integration, cursor.integration_id)
                if failed_integration is not None:
                    was_degraded = failed_integration.status == "degraded"
                    failed_integration.status = "degraded"
                    failed_integration.last_error_code = getattr(e, "code", "sync_failed")
                    failed_integration.last_error_at = now
                    db.add(failed_integration)
                    if not was_degraded:
                        pipeline.evaluate_alert_rules(db, workspace_id=failed_integration.workspace_id,
                            event_type="integration.disconnected", integration=failed_integration)
                db.commit()
        except Exception:
            db.rollback()
        return 0
    finally:
        db.close()

def _apply_sync_page(db, integration: Integration, cursor: SyncCursor, page, now) -> int:
    from app.models.models import Execution

    count = 0
    if cursor.resource_type == "workflows":
        for item in page.items:
            wf = db.execute(
                select(Workflow).where(
                    Workflow.integration_id == integration.id,
                    Workflow.external_id == item.external_id,
                    Workflow.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if wf is None:
                wf = Workflow(
                    workspace_id=integration.workspace_id,
                    integration_id=integration.id,
                    external_id=item.external_id,
                    name=item.name,
                    description=item.description,
                    environment=item.environment,
                    is_active=item.is_active,
                    provider_metadata=item.provider_metadata,
                    last_synced_at=now,
                )
            else:
                local_meta = wf.provider_metadata or {}
                if not local_meta.get("_name_override"):
                    wf.name = item.name
                if not local_meta.get("_environment_override"):
                    wf.environment = item.environment
                wf.is_active = item.is_active if item.is_active is not None else wf.is_active
                if item.description is not None:
                    wf.description = item.description
                wf.provider_metadata = {**item.provider_metadata, **{k:v for k,v in local_meta.items() if k in ("_environment_override", "_name_override")}}
                wf.last_synced_at = now
            db.add(wf)
            count += 1
        pipeline.emit_event(
            db,
            integration.workspace_id,
            "integrations.synced",
            {"integration_id": str(integration.id), "workflows": count},
        )
        return count

    # executions tail
    for item in sorted(page.items, key=lambda item: item.started_at or now):
        wf = db.execute(
            select(Workflow).where(
                Workflow.integration_id == integration.id,
                Workflow.external_id == str((item.provider_metadata or {}).get("workflowId", "")),
                Workflow.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if wf is None:
            external_id = str((item.provider_metadata or {}).get("workflowId", ""))
            if not external_id:
                continue
            wf = Workflow(workspace_id=integration.workspace_id, integration_id=integration.id,
                external_id=external_id, name=f"Workflow {external_id}")
            db.add(wf)
            db.flush()
        if not wf.monitoring_enabled:
            continue
        existing = (
            db.execute(
                select(Execution).where(
                    Execution.workflow_id == wf.id, Execution.external_id == item.external_id
                )
            ).scalar_one_or_none()
            if item.external_id
            else None
        )
        prev_status = existing.status if existing is not None else None
        duration = item.duration_ms
        if duration is None and item.started_at and item.finished_at:
            duration = int((item.finished_at - item.started_at).total_seconds() * 1000)
        if existing is None:
            execution = Execution(
                workspace_id=integration.workspace_id,
                workflow_id=wf.id,
                external_id=item.external_id,
                status=item.status,
                started_at=item.started_at,
                finished_at=item.finished_at,
                duration_ms=duration,
                failed_node=item.failed_node,
                error_class=item.error_class,
                error_code=item.error_code,
                source_url=item.source_url,
                error_message_redacted=item.error_message_redacted,
                source_retry_of=item.source_retry_of,
                mode=item.mode,
                provider_metadata=item.provider_metadata,
            )
            db.add(execution)
            db.flush()
            count += 1
        else:
            execution = existing
            execution.status = item.status
            execution.started_at = item.started_at or execution.started_at
            execution.finished_at = item.finished_at or execution.finished_at
            execution.duration_ms = duration if duration is not None else execution.duration_ms
            if item.failed_node:
                execution.failed_node = item.failed_node
            if item.source_url:
                execution.source_url = item.source_url
            if item.error_code:
                execution.error_code = item.error_code
            if item.error_class:
                execution.error_class = item.error_class
            if item.error_message_redacted:
                execution.error_message_redacted = item.error_message_redacted
            execution.last_observed_at = now
            db.add(execution)

        if item.status == "failed" and prev_status != "failed":
            incident = pipeline.classify_incident(
                db,
                workspace_id=integration.workspace_id,
                integration=integration,
                workflow=wf,
                execution=execution,
                error_message=item.error_message_redacted,
                error_class=item.error_class,
                failed_node=item.failed_node,
            )
            pipeline.evaluate_alert_rules(
                db,
                workspace_id=integration.workspace_id,
                event_type="execution.failed",
                incident=incident,
                workflow=wf,
            )
            if incident.occurrence_count == 1:
                pipeline.evaluate_alert_rules(db, workspace_id=integration.workspace_id,
                    event_type="incident.created", incident=incident, workflow=wf)
        elif item.status == "success" and prev_status != "success":
            pipeline.process_success(
                db,
                workspace_id=integration.workspace_id,
                integration=integration,
                workflow=wf,
                execution=execution,
            )
    pipeline.emit_event(
        db,
        integration.workspace_id,
        "executions.updated",
        {"integration_id": str(integration.id), "observed": count},
    )
    return count

def run_worker_once() -> dict[str, int]:
    return {
        "events": drain_outbox_once(),
        "notifications": deliver_notifications_once(),
        "syncs": sync_integrations_once(),
    }


def run_worker_loop(stop_event: threading.Event) -> None:
    import time
    from app.modules.retention import run_retention_once
    from app.modules.status_alerts import evaluate_status_alerts_once
    last_sweep = 0.0
    interval = max(config.settings.worker_interval_seconds, 0.2)
    while not stop_event.is_set():
        try:
            run_worker_once()
            if time.monotonic() - last_sweep >= 60:
                run_retention_once()
                evaluate_status_alerts_once()
                last_sweep = time.monotonic()
        except Exception:
            logger.exception("worker loop iteration failed")
        stop_event.wait(interval)


def start_worker_thread(stop_event: threading.Event | None = None) -> threading.Thread | None:
    if not config.settings.worker_enabled or not config.settings.worker_embedded:
        return None
    stop_event = stop_event or threading.Event()

    def runner() -> None:
        try:
            run_worker_loop(stop_event)
        except Exception:
            logger.exception("worker thread exited unexpectedly")

    thread = threading.Thread(target=runner, name="flowsentry-worker", daemon=True)
    thread.start()
    logger.info("embedded worker started")
    return thread
