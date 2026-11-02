"""Analytics endpoints (API_SPECIFICATION.md section 13).

All windows are computed in UTC. Executions with unknown status are excluded
from success-rate denominators — the rule is documented in each response.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.deps import get_db_session, get_membership
from app.models.models import (
    Execution,
    Incident,
    Integration,
    Workflow,
    WorkspaceMember,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(
    window_hours: int = Query(default=24, ge=1, le=720),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    ws = member.workspace_id
    now = utcnow()
    since = now - timedelta(hours=window_hours)

    total = db.execute(
        select(func.count(Execution.id)).where(Execution.workspace_id == ws, func.coalesce(Execution.started_at, Execution.first_observed_at) >= since)
    ).scalar() or 0
    ok = db.execute(
        select(func.count(Execution.id)).where(
            Execution.workspace_id == ws, func.coalesce(Execution.started_at, Execution.first_observed_at) >= since, Execution.status == "success"
        )
    ).scalar() or 0
    failed = db.execute(
        select(func.count(Execution.id)).where(
            Execution.workspace_id == ws, func.coalesce(Execution.started_at, Execution.first_observed_at) >= since, Execution.status == "failed"
        )
    ).scalar() or 0
    open_incidents = db.execute(
        select(func.count(Incident.id)).where(
            Incident.workspace_id == ws, Incident.status.in_(("open", "acknowledged", "investigating", "recovering"))
        )
    ).scalar() or 0
    monitored = db.execute(
        select(func.count(Workflow.id)).where(
            Workflow.workspace_id == ws, Workflow.deleted_at.is_(None), Workflow.monitoring_enabled.is_(True)
        )
    ).scalar() or 0
    disconnected = db.execute(
        select(func.count(Integration.id)).where(
            Integration.workspace_id == ws,
            Integration.deleted_at.is_(None),
            Integration.status.in_(("disconnected", "error")),
        )
    ).scalar() or 0
    # Rule: success_rate excludes unknown/running/waiting executions.
    known = ok + failed
    return {
        "data": {
            "window_hours": window_hours,
            "total_executions": total,
            "successful_executions": ok,
            "failed_executions": failed,
            "success_rate": round(ok / known, 4) if known else None,
            "open_incidents": open_incidents,
            "monitored_workflows": monitored,
            "disconnected_integrations": disconnected,
            "success_rate_rule": "successful / (successful + failed); unknown statuses excluded",
        },
        "meta": {"request_id": None},
    }


@router.get("/executions")
def executions_series(
    window_hours: int = Query(default=24, ge=1, le=720),
    bucket_hours: int = Query(default=1, ge=1, le=72),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    since = utcnow() - timedelta(hours=window_hours)
    sql = text(
        """
        WITH buckets AS (
            SELECT generate_series(
                date_bin(make_interval(hours => :hours), CAST(:since AS timestamptz), '2000-01-01'::timestamptz),
                date_bin(make_interval(hours => :hours), CAST(:now AS timestamptz), '2000-01-01'::timestamptz),
                make_interval(hours => :hours)) AS bucket
        ), counts AS (
            SELECT date_bin(make_interval(hours => :hours), coalesce(started_at, first_observed_at), '2000-01-01'::timestamptz) AS bucket,
                count(*) FILTER (WHERE status = 'success') AS success,
                count(*) FILTER (WHERE status = 'failed') AS failed
            FROM executions WHERE workspace_id = :ws
                AND coalesce(started_at, first_observed_at) >= :since
                AND coalesce(started_at, first_observed_at) <= :now GROUP BY 1
        ) SELECT buckets.bucket, coalesce(counts.success, 0), coalesce(counts.failed, 0)
        FROM buckets LEFT JOIN counts USING (bucket) ORDER BY 1
        """
    )
    rows = db.execute(sql, {"ws": member.workspace_id, "since": since, "now": utcnow(), "hours": bucket_hours}).all()
    return {
        "data": [
            {"bucket": r[0].isoformat() if r[0] else None, "success": r[1], "failed": r[2]}
            for r in rows
        ],
        "meta": {"request_id": None},
    }


@router.get("/failures")
def failures(
    window_hours: int = Query(default=24, ge=1, le=720),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    since = utcnow() - timedelta(hours=window_hours)
    by_workflow = db.execute(
        select(Workflow.name, func.count(Execution.id))
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .where(
            Execution.workspace_id == member.workspace_id,
            Execution.status == "failed",
            func.coalesce(Execution.started_at, Execution.first_observed_at) >= since,
        )
        .group_by(Workflow.name)
        .order_by(func.count(Execution.id).desc())
        .limit(10)
    ).all()
    by_error = db.execute(
        select(Execution.error_class, func.count(Execution.id))
        .where(
            Execution.workspace_id == member.workspace_id,
            Execution.status == "failed",
            func.coalesce(Execution.started_at, Execution.first_observed_at) >= since,
            Execution.error_class.isnot(None),
        )
        .group_by(Execution.error_class)
        .order_by(func.count(Execution.id).desc())
        .limit(10)
    ).all()
    slowest = db.execute(
        select(Workflow.name, func.round(func.avg(Execution.duration_ms), 0))
        .join(Workflow, Workflow.id == Execution.workflow_id)
        .where(
            Execution.workspace_id == member.workspace_id,
            func.coalesce(Execution.started_at, Execution.first_observed_at) >= since,
            Execution.duration_ms.isnot(None),
        )
        .group_by(Workflow.name)
        .order_by(func.avg(Execution.duration_ms).desc())
        .limit(5)
    ).all()
    severity_dist = db.execute(
        select(Incident.severity, func.count(Incident.id))
        .where(
            Incident.workspace_id == member.workspace_id,
            Incident.first_seen_at >= since,
        )
        .group_by(Incident.severity)
    ).all()
    return {
        "data": {
            "failures_by_workflow": [{"workflow": n, "count": c} for n, c in by_workflow],
            "top_error_classes": [{"error_class": e, "count": c} for e, c in by_error],
            "slowest_workflows": [{"workflow": n, "avg_duration_ms": int(d) if d is not None else None} for n, d in slowest],
            "incident_severity": [{"severity": s, "count": c} for s, c in severity_dist],
        },
        "meta": {"request_id": None},
    }


@router.get("/workflows")
def workflow_ranking(
    window_hours: int = Query(default=168, ge=1, le=720),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    since = utcnow() - timedelta(hours=window_hours)
    rows = db.execute(
        select(
            Workflow.id,
            Workflow.name,
            Workflow.criticality,
            func.count(Execution.id),
            func.count(Execution.id).filter(Execution.status == "success"),
            func.count(Execution.id).filter(Execution.status == "failed"),
            func.round(func.avg(Execution.duration_ms), 0),
        )
        .outerjoin(Execution, (Execution.workflow_id == Workflow.id) & (func.coalesce(Execution.started_at, Execution.first_observed_at) >= since))
        .where(Workflow.workspace_id == member.workspace_id, Workflow.deleted_at.is_(None))
        .group_by(Workflow.id, Workflow.name, Workflow.criticality)
        .order_by(func.count(Execution.id).filter(Execution.status == "failed").desc())
        .limit(50)
    ).all()
    data = []
    for wid, name, crit, total, ok, failed, avg_ms in rows:
        known = ok + failed
        data.append(
            {
                "workflow_id": str(wid),
                "name": name,
                "criticality": crit,
                "total_executions": total,
                "success_count": ok,
                "failure_count": failed,
                "success_rate": round(ok / known, 4) if known else None,
                "avg_duration_ms": int(avg_ms) if avg_ms is not None else None,
            }
        )
    return {"data": data, "meta": {"request_id": None}}


@router.get("/incidents")
def incident_trends(
    window_hours: int = Query(default=168, ge=1, le=720),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    since = utcnow() - timedelta(hours=window_hours)
    created = db.execute(
        select(func.count(Incident.id)).where(
            Incident.workspace_id == member.workspace_id, Incident.first_seen_at >= since
        )
    ).scalar() or 0
    resolved = db.execute(
        select(func.count(Incident.id)).where(
            Incident.workspace_id == member.workspace_id,
            Incident.resolved_at >= since,
        )
    ).scalar() or 0
    mtta = db.execute(
        text(
            "SELECT avg(extract(epoch FROM (acknowledged_at - first_seen_at))) FROM incidents "
            "WHERE workspace_id = :ws AND acknowledged_at IS NOT NULL AND first_seen_at >= :since"
        ),
        {"ws": member.workspace_id, "since": since},
    ).scalar()
    mttr = db.execute(
        text(
            "SELECT avg(extract(epoch FROM (resolved_at - first_seen_at))) FROM incidents "
            "WHERE workspace_id = :ws AND resolved_at IS NOT NULL AND first_seen_at >= :since"
        ),
        {"ws": member.workspace_id, "since": since},
    ).scalar()
    return {
        "data": {
            "window_hours": window_hours,
            "incidents_created": created,
            "incidents_resolved": resolved,
            "mtta_seconds": round(mtta, 1) if mtta is not None else None,
            "mttr_seconds": round(mttr, 1) if mttr is not None else None,
        },
        "meta": {"request_id": None},
    }
