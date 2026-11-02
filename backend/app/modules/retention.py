"""Bounded retention. Never removes incident/recovery evidence or pending work."""
from datetime import timedelta
from sqlalchemy import select, delete, update, exists, text
from app.core import config
from app.core.db import get_session_factory,utcnow
from app.models.models import InboundEvent,OutboxMessage,Execution,IncidentExecution,RecoveryAction,WorkflowHealthSnapshot

def run_retention_once(batch_size:int=500)->dict[str,int]:
    size=max(1,min(batch_size,1000))
    now=utcnow()
    counts={"payloads_cleared":0,"executions_removed":0,"outbox_removed":0,"snapshots_removed":0}
    with get_session_factory()() as db:
        if not db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('flowsentry-retention'))")).scalar():
            return counts
        ids=db.execute(select(InboundEvent.id).where(InboundEvent.received_at<now-timedelta(seconds=config.settings.retention_event_payload_seconds),InboundEvent.processing_status=="processed",InboundEvent.payload_redacted.is_not(None)).order_by(InboundEvent.received_at).limit(size).with_for_update(skip_locked=True)).scalars().all()
        if ids:
            counts['payloads_cleared']=db.execute(update(InboundEvent).where(InboundEvent.id.in_(ids)).values(payload_redacted=None)).rowcount
        ids=db.execute(select(Execution.id).where(Execution.first_observed_at<now-timedelta(seconds=config.settings.retention_execution_seconds),Execution.status.in_(['success','failed','canceled']),~exists(select(IncidentExecution.execution_id).where(IncidentExecution.execution_id==Execution.id)),~exists(select(RecoveryAction.id).where(RecoveryAction.execution_id==Execution.id))).order_by(Execution.first_observed_at).limit(size).with_for_update(skip_locked=True)).scalars().all()
        if ids:
            counts['executions_removed']=db.execute(delete(Execution).where(Execution.id.in_(ids))).rowcount
        ids=db.execute(select(OutboxMessage.id).where(OutboxMessage.published_at.is_not(None),OutboxMessage.created_at<now-timedelta(days=7)).order_by(OutboxMessage.created_at).limit(size).with_for_update(skip_locked=True)).scalars().all()
        if ids:
            counts['outbox_removed']=db.execute(delete(OutboxMessage).where(OutboxMessage.id.in_(ids))).rowcount
        ids=db.execute(select(WorkflowHealthSnapshot.id).where(WorkflowHealthSnapshot.calculated_at<now-timedelta(days=90)).order_by(WorkflowHealthSnapshot.calculated_at).limit(size)).scalars().all()
        if ids:
            counts['snapshots_removed']=db.execute(delete(WorkflowHealthSnapshot).where(WorkflowHealthSnapshot.id.in_(ids))).rowcount
        db.commit()
    return counts
