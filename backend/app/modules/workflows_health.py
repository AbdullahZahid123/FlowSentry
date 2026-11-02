"""Workflow health computation (API_SPECIFICATION.md section 10.2).

Pure rule-based scoring over the trailing 24-hour window — never a client
input. Results are persisted as WorkflowHealthSnapshot rows so trends can be
queried later. Unknown-status executions are excluded from the success-rate
denominator (documented in the response).
"""

from __future__ import annotations

import uuid
import math
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.models.models import Execution, Workflow, WorkflowHealthSnapshot

WINDOW_SECONDS = 24 * 3600
STATE_DEGRADED_AT = 0.8
STATE_CRITICAL_AT = 0.5


def _percentile95(values: list[int]) -> int | None:
    if not values:
        return None
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, math.ceil(len(vals) * 0.95) - 1))
    return vals[idx]


def compute_health(db: OrmSession, workflow: Workflow) -> dict[str, Any]:
    now = utcnow()
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    rows = (
        db.execute(
            select(Execution.status, Execution.duration_ms,
                func.coalesce(Execution.started_at, Execution.first_observed_at).label("started_at"), Execution.finished_at)
            .where(
                Execution.workflow_id == workflow.id,
                func.coalesce(Execution.started_at, Execution.first_observed_at) >= window_start,
            )
        )
        .all()
    )
    total = len(rows)
    success = sum(1 for r in rows if r.status == "success")
    failed = sum(1 for r in rows if r.status == "failed")
    known = success + failed
    durations = [int(r.duration_ms) for r in rows if r.duration_ms is not None]
    last_failed_at = max((r.started_at for r in rows if r.status == "failed"), default=None)
    last_success_at = max((r.started_at for r in rows if r.status == "success"), default=None)

    success_rate = (success / known) if known else None
    avg_duration = (sum(durations) / len(durations)) if durations else None
    p95_duration = _percentile95(durations)

    signals: dict[str, Any] = {
        "success_rate_rule": "successful / (successful + failed); unknown statuses excluded",
        "failure_rate": (failed / known) if known else None,
        "last_failed_at": last_failed_at.isoformat() if last_failed_at else None,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "expected_interval_seconds": workflow.expected_interval_seconds,
        "stale": None,
        "inactive_flag": workflow.is_active,
    }

    state = "unknown"
    if workflow.is_active is False or not workflow.monitoring_enabled:
        state = "inactive"
    elif known:
        if success_rate is not None and success_rate < STATE_CRITICAL_AT:
            state = "critical"
        elif success_rate is not None and success_rate < STATE_DEGRADED_AT:
            state = "degraded"
        else:
            state = "healthy"
    if workflow.expected_interval_seconds and workflow.is_active is not False:
        last_seen = max((d for d in (last_failed_at, last_success_at) if d is not None), default=None)
        if last_seen and (now - last_seen).total_seconds() > 3 * workflow.expected_interval_seconds:
            signals["stale"] = True
            state = "unknown" if state == "healthy" else state

    score: float | None = None
    if success_rate is not None:
        score = round(float(success_rate) * 100.0, 2)

    window_end = now
    existing = db.execute(
        select(WorkflowHealthSnapshot.id).where(
            WorkflowHealthSnapshot.workflow_id == workflow.id,
            WorkflowHealthSnapshot.window_start == window_start,
            WorkflowHealthSnapshot.window_end == window_end,
        )
    ).scalar_one_or_none()
    snapshot = (
        db.get(WorkflowHealthSnapshot, existing)
        if existing
        else WorkflowHealthSnapshot(
            workspace_id=workflow.workspace_id,
            workflow_id=workflow.id,
            window_start=window_start,
            window_end=window_end,
        )
    )
    snapshot.total_executions = total
    snapshot.success_count = success
    snapshot.failure_count = failed
    snapshot.success_rate = success_rate
    snapshot.avg_duration_ms = avg_duration
    snapshot.p95_duration_ms = p95_duration
    snapshot.health_state = state
    snapshot.health_score = score
    snapshot.signals = signals
    snapshot.calculated_at = now
    db.add(snapshot)
    db.commit()

    return {
        "workflow_id": str(workflow.id),
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "total_executions": total,
        "success_count": success,
        "failure_count": failed,
        "success_rate": round(success_rate, 4) if success_rate is not None else None,
        "avg_duration_ms": round(avg_duration, 2) if avg_duration is not None else None,
        "p95_duration_ms": p95_duration,
        "health_state": state,
        "health_score": score,
        "signals": signals,
    }
