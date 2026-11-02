"""Periodic inactivity rules using source activity and expected run intervals."""
from datetime import timedelta
from sqlalchemy import select, func
from app.core.db import get_session_factory, utcnow, advisory_xact_lock
from app.models.models import Execution, Workflow, Integration
from app.modules.pipeline import evaluate_alert_rules


def evaluate_status_alerts_once():
    now=utcnow();queued=0
    with get_session_factory()() as db:
        advisory_xact_lock(db,'status-alerts')
        latest=select(Execution.workflow_id,func.max(func.coalesce(Execution.started_at,Execution.first_observed_at)).label('last_run')).group_by(Execution.workflow_id).subquery()
        rows=db.execute(select(Workflow,latest.c.last_run).outerjoin(latest,latest.c.workflow_id==Workflow.id).join(Integration,Integration.id==Workflow.integration_id).where(
            Workflow.monitoring_enabled.is_(True),Workflow.deleted_at.is_(None),Integration.enabled.is_(True),Integration.deleted_at.is_(None)))
        for workflow,last_run in rows:
            stale=bool(workflow.expected_interval_seconds and now-(last_run or workflow.created_at)>timedelta(seconds=3*workflow.expected_interval_seconds))
            if workflow.is_active is False or stale:
                queued+=evaluate_alert_rules(db,workspace_id=workflow.workspace_id,event_type='workflow.inactive',workflow=workflow)
        db.commit()
    return queued
