"""Alert rules, notification channels, and delivery history
(API_SPECIFICATION.md section 12)."""

from __future__ import annotations

import uuid
import math

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core import config
from app.core.db import utcnow
from app.core.egress import validate_webhook_destination
from app.core.errors import ApiError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.deps import get_db_session, get_membership, require_role
from app.models.models import (
    AlertRule,
    AlertRuleChannel,
    Notification,
    NotificationAttempt,
    NotificationChannel,
    WorkspaceMember,
)
from app.modules import audit
from app.schemas.common import AlertRuleCreate, AlertRuleUpdate, ChannelCreate, ChannelUpdate

router = APIRouter(tags=["alerts"])

ALLOWED_EVENT_TYPES = {
    "execution.failed",
    "incident.created",
    "incident.escalated",
    "incident.resolved",
    "integration.disconnected",
    "workflow.inactive",
}
ALLOWED_CONDITION_KEYS = {
    "workflow_criticality_in",
    "consecutive_failures_gte",
    "failure_rate_gte",
    "severity_at_least",
}
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def validate_conditions(conditions: dict | None) -> dict | None:
    """Versioned rule-schema validation. No arbitrary expressions (API_SPEC 12.1)."""
    if not conditions:
        return None
    if not isinstance(conditions, dict):
        raise ApiError("validation_error", "conditions must be an object.", 422)
    unknown = set(conditions) - ALLOWED_CONDITION_KEYS
    if unknown:
        raise ApiError("validation_error", f"Unknown condition keys: {sorted(unknown)}", 422)
    if "workflow_criticality_in" in conditions:
        vals = conditions["workflow_criticality_in"]
        if not isinstance(vals, list) or any(v not in ("critical", "high", "normal", "low") for v in vals):
            raise ApiError("validation_error", "workflow_criticality_in contains invalid values.", 422)
    for k in ("consecutive_failures_gte", "failure_rate_gte"):
        if k in conditions:
            value = conditions[k]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ApiError("validation_error", f"{k} must be a finite number.", 422)
            if k == "failure_rate_gte" and not 0 <= value <= 1:
                raise ApiError("validation_error", "failure_rate_gte must be between 0 and 1.", 422)
            if k == "consecutive_failures_gte" and (int(value) != value or not 1 <= value <= 1000):
                raise ApiError("validation_error", "consecutive_failures_gte must be an integer from 1 to 1000.", 422)
    if "severity_at_least" in conditions and conditions["severity_at_least"] not in SEVERITY_RANK:
        raise ApiError("validation_error", "severity_at_least is invalid.", 422)
    return conditions


# --- alert rules ---------------------------------------------------------------

rules_router = APIRouter(prefix="/alert-rules", tags=["alerts"])


def _rule_payload(db: OrmSession, r: AlertRule) -> dict:
    channel_ids = [
        str(row[0])
        for row in db.execute(
            select(AlertRuleChannel.notification_channel_id).where(
                AlertRuleChannel.alert_rule_id == r.id
            )
        ).all()
    ]
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "enabled": r.enabled,
        "event_types": r.event_types,
        "conditions": r.conditions,
        "severity_minimum": r.severity_minimum,
        "cooldown_seconds": r.cooldown_seconds,
        "channel_ids": channel_ids,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _load_rule(db: OrmSession, rule_id: uuid.UUID, workspace_id: uuid.UUID) -> AlertRule:
    r = db.execute(
        select(AlertRule).where(
            AlertRule.id == rule_id, AlertRule.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if r is None:
        raise ApiError("resource_not_found", "Alert rule not found.", 404)
    return r


def _resolve_channels(db: OrmSession, workspace_id: uuid.UUID, channel_ids: list[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for cid in channel_ids:
        try:
            cuuid = uuid.UUID(cid)
        except ValueError as e:
            raise ApiError("validation_error", f"Invalid channel id: {cid}", 422) from e
        ch = db.execute(
            select(NotificationChannel).where(
                NotificationChannel.id == cuuid,
                NotificationChannel.workspace_id == workspace_id,
            )
        ).scalar_one_or_none()
        if ch is None:
            raise ApiError("validation_error", f"Channel {cid} was not found in this workspace.", 422)
        out.append(cuuid)
    return out


@rules_router.get("")
def list_rules(
    member: WorkspaceMember = Depends(get_membership), db: OrmSession = Depends(get_db_session)
) -> dict:
    rows = (
        db.execute(
            select(AlertRule)
            .where(AlertRule.workspace_id == member.workspace_id)
            .order_by(AlertRule.created_at)
        )
        .scalars()
        .all()
    )
    return {"data": [_rule_payload(db, r) for r in rows], "meta": {"request_id": None}}


@rules_router.post("", status_code=201)
def create_rule(
    payload: AlertRuleCreate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    invalid = set(payload.event_types) - ALLOWED_EVENT_TYPES
    if invalid:
        raise ApiError("validation_error", f"Unknown event types: {sorted(invalid)}", 422)
    channel_ids = _resolve_channels(db, member.workspace_id, payload.channel_ids)
    rule = AlertRule(
        workspace_id=member.workspace_id,
        name=payload.name,
        description=payload.description,
        enabled=payload.enabled,
        event_types=payload.event_types,
        conditions=validate_conditions(payload.conditions),
        severity_minimum=payload.severity_minimum,
        cooldown_seconds=payload.cooldown_seconds,
        created_by=member.user_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(rule)
    db.flush()
    for cid in channel_ids:
        db.add(AlertRuleChannel(alert_rule_id=rule.id, notification_channel_id=cid))
    audit.record_audit(
        db,
        action="alert_rule.created",
        resource_type="alert_rule",
        resource_id=rule.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _rule_payload(db, rule), "meta": {"request_id": request.state.request_id}}


@rules_router.get("/{rule_id}")
def get_rule(
    rule_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    return {"data": _rule_payload(db, _load_rule(db, rule_id, member.workspace_id)), "meta": {"request_id": None}}


@rules_router.patch("/{rule_id}")
def update_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    r = _load_rule(db, rule_id, member.workspace_id)
    if payload.event_types is not None:
        invalid = set(payload.event_types) - ALLOWED_EVENT_TYPES
        if invalid:
            raise ApiError("validation_error", f"Unknown event types: {sorted(invalid)}", 422)
        r.event_types = payload.event_types
    if payload.conditions is not None:
        r.conditions = validate_conditions(payload.conditions)
    if payload.severity_minimum is not None:
        r.severity_minimum = payload.severity_minimum
    if payload.cooldown_seconds is not None:
        r.cooldown_seconds = payload.cooldown_seconds
    if payload.name is not None:
        r.name = payload.name
    if payload.description is not None:
        r.description = payload.description
    if payload.enabled is not None:
        r.enabled = payload.enabled
    r.updated_at = utcnow()
    db.add(r)
    if payload.channel_ids is not None:
        channel_ids = _resolve_channels(db, member.workspace_id, payload.channel_ids)
        for row in db.execute(select(AlertRuleChannel).where(AlertRuleChannel.alert_rule_id == r.id)).scalars():
            db.delete(row)
        for cid in channel_ids:
            db.add(AlertRuleChannel(alert_rule_id=r.id, notification_channel_id=cid))
    audit.record_audit(
        db,
        action="alert_rule.updated",
        resource_type="alert_rule",
        resource_id=r.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _rule_payload(db, r), "meta": {"request_id": request.state.request_id}}


@rules_router.delete("/{rule_id}", status_code=204)
def delete_rule(
    rule_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> None:
    r = _load_rule(db, rule_id, member.workspace_id)
    for row in db.execute(select(AlertRuleChannel).where(AlertRuleChannel.alert_rule_id == r.id)).scalars():
        db.delete(row)
    # Preserve delivery history and its foreign key to this rule.
    r.enabled = False
    db.add(r)
    audit.record_audit(
        db,
        action="alert_rule.deleted",
        resource_type="alert_rule",
        resource_id=rule_id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return Response(status_code=204)


# --- channels ------------------------------------------------------------------

channels_router = APIRouter(prefix="/notification-channels", tags=["notifications"])


def _channel_payload(c: NotificationChannel) -> dict:
    return {
        "id": str(c.id),
        "channel_type": c.channel_type,
        "name": c.name,
        "destination_label": c.destination_label,
        "enabled": c.enabled,
        "last_tested_at": c.last_tested_at.isoformat() if c.last_tested_at else None,
        "last_test_status": c.last_test_status,
        "created_at": c.created_at.isoformat(),
    }


def _validate_channel_config(channel_type: str, config_map: dict) -> tuple[dict, str]:
    """Validate configuration and return (sanitized, destination_label)."""
    if not isinstance(config_map, dict):
        raise ApiError("validation_error", "configuration must be an object.", 422)
    if channel_type == "email":
        to = config_map.get("to")
        if not to or "@" not in str(to):
            raise ApiError("validation_error", "An email recipient is required.", 422)
        return {"to": str(to)}, str(to)
    if channel_type == "telegram":
        chat_id = config_map.get("chat_id")
        if not chat_id:
            raise ApiError("validation_error", "A telegram chat_id is required.", 422)
        return {"chat_id": str(chat_id)}, f"chat {chat_id}"
    if channel_type == "webhook":
        url = config_map.get("url")
        if not url:
            raise ApiError("validation_error", "A webhook URL is required.", 422)
        url = validate_webhook_destination(str(url))
        return {"url": url}, url
    if channel_type == "log":
        return {}, "server log"
    raise ApiError("validation_error", "Unsupported channel type.", 422)


@channels_router.get("")
def list_channels(
    member: WorkspaceMember = Depends(get_membership), db: OrmSession = Depends(get_db_session)
) -> dict:
    rows = (
        db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.workspace_id == member.workspace_id)
            .order_by(NotificationChannel.created_at)
        )
        .scalars()
        .all()
    )
    return {"data": [_channel_payload(c) for c in rows], "meta": {"request_id": None}}


@channels_router.post("", status_code=201)
def create_channel(
    payload: ChannelCreate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    sanitized, label = _validate_channel_config(payload.channel_type, payload.configuration)
    import json

    ciphertext, key_version = encrypt_secret(json.dumps(sanitized))
    channel = NotificationChannel(
        workspace_id=member.workspace_id,
        channel_type=payload.channel_type,
        name=payload.name,
        configuration_ciphertext=ciphertext,
        configuration_key_version=key_version,
        destination_label=label,
        enabled=payload.enabled,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(channel)
    db.flush()
    audit.record_audit(
        db,
        action="notification_channel.created",
        resource_type="notification_channel",
        resource_id=channel.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"channel_type": payload.channel_type},
    )
    db.commit()
    return {"data": _channel_payload(channel), "meta": {"request_id": request.state.request_id}}


def _load_channel(db: OrmSession, channel_id: uuid.UUID, workspace_id: uuid.UUID) -> NotificationChannel:
    c = db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if c is None:
        raise ApiError("resource_not_found", "Notification channel not found.", 404)
    return c


@channels_router.patch("/{channel_id}")
def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    c = _load_channel(db, channel_id, member.workspace_id)
    if payload.name is not None:
        c.name = payload.name
    if payload.enabled is not None:
        c.enabled = payload.enabled
    if payload.configuration is not None:
        sanitized, label = _validate_channel_config(c.channel_type, payload.configuration)
        import json

        ciphertext, key_version = encrypt_secret(json.dumps(sanitized))
        c.configuration_ciphertext = ciphertext
        c.configuration_key_version = key_version
        c.destination_label = label
    c.updated_at = utcnow()
    db.add(c)
    audit.record_audit(
        db,
        action="notification_channel.updated",
        resource_type="notification_channel",
        resource_id=c.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _channel_payload(c), "meta": {"request_id": request.state.request_id}}


@channels_router.delete("/{channel_id}", status_code=204)
def delete_channel(
    channel_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> None:
    c = _load_channel(db, channel_id, member.workspace_id)
    c.enabled = False
    c.updated_at = utcnow()
    for row in db.execute(
        select(AlertRuleChannel).where(AlertRuleChannel.notification_channel_id == c.id)
    ).scalars():
        db.delete(row)
    # Keep the disabled channel so historical deliveries remain inspectable.
    c.configuration_ciphertext = None
    c.configuration_key_version = None
    db.add(c)
    audit.record_audit(
        db,
        action="notification_channel.deleted",
        resource_type="notification_channel",
        resource_id=channel_id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return Response(status_code=204)


@channels_router.post("/{channel_id}/test")
def test_channel(
    channel_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    import json

    from app.modules.notify_send import send_notification_payload

    c = _load_channel(db, channel_id, member.workspace_id)
    if not c.enabled:
        raise ApiError("conflict", "This channel is disabled.", 409)
    config_map: dict = {}
    if c.configuration_ciphertext:
        config_map = json.loads(decrypt_secret(c.configuration_ciphertext))
    try:
        ok, err = send_notification_payload(
            c.channel_type, config_map, "FlowSentry test notification", "This is a test delivery from FlowSentry."
        )
        c.last_tested_at = utcnow()
        c.last_test_status = "delivered" if ok else "failed"
        db.add(c)
        db.commit()
        if not ok:
            return {
                "data": {"status": "failed", "error": err},
                "meta": {"request_id": request.state.request_id},
            }
        return {"data": {"status": "delivered"}, "meta": {"request_id": request.state.request_id}}
    except Exception as e:
        c.last_tested_at = utcnow()
        c.last_test_status = "failed"
        db.add(c)
        db.commit()
        return {
            "data": {"status": "failed", "error": "Delivery failed; see server logs."},
            "meta": {"request_id": request.state.request_id},
        }


# --- notification history ---------------------------------------------------------


notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


@notifications_router.get("")
def list_notifications(
    status: str | None = None,
    incident_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    q = (
        select(Notification)
        .where(Notification.workspace_id == member.workspace_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Notification.status == status)
    if incident_id:
        q = q.where(Notification.incident_id == incident_id)
    rows = db.execute(q).scalars().all()
    return {
        "data": [
            {
                "id": str(n.id),
                "incident_id": str(n.incident_id) if n.incident_id else None,
                "channel_id": str(n.channel_id),
                "status": n.status,
                "subject": n.subject,
                "body_redacted": n.body_redacted,
                "attempt_count": n.attempt_count,
                "next_attempt_at": n.next_attempt_at.isoformat() if n.next_attempt_at else None,
                "delivered_at": n.delivered_at.isoformat() if n.delivered_at else None,
                "last_error": n.last_error,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
        "meta": {"request_id": None},
    }


@notifications_router.get("/{notification_id}")
def get_notification(
    notification_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    n = db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.workspace_id == member.workspace_id,
        )
    ).scalar_one_or_none()
    if n is None:
        raise ApiError("resource_not_found", "Notification not found.", 404)
    attempts = (
        db.execute(
            select(NotificationAttempt)
            .where(NotificationAttempt.notification_id == n.id)
            .order_by(NotificationAttempt.attempt_number)
        )
        .scalars()
        .all()
    )
    return {
        "data": {
            "id": str(n.id),
            "status": n.status,
            "subject": n.subject,
            "body_redacted": n.body_redacted,
            "attempt_count": n.attempt_count,
            "delivered_at": n.delivered_at.isoformat() if n.delivered_at else None,
            "last_error": n.last_error,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "status": a.status,
                    "http_status": a.http_status,
                    "error_code": a.error_code,
                    "error_message": a.error_message,
                    "started_at": a.started_at.isoformat(),
                    "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                }
                for a in attempts
            ],
        },
        "meta": {"request_id": None},
    }
