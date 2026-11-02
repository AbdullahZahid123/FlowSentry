"""Ingestion endpoints: authenticated event acceptance from automation
platforms (API_SPECIFICATION.md section 8).

Critical requirement (PRD 9.6): an event is acknowledged only after it is
durably persisted. Duplicate deliveries return the original event id with
`duplicate: true` — no duplicate processing.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.adapters.n8n.adapter import get_adapter
from app.core import config
from app.core.db import utcnow
from app.core.errors import ApiError
from app.core.fingerprint import compute_event_dedupe_key
from app.core.ratelimit import allow
from app.core.redaction import payload_hash, redact_value
from app.core.security import constant_time_eq_bytes, hash_token
from app.models.models import InboundEvent, Integration, OutboxMessage
from app.deps import get_db_session

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _authenticate_integration(db: OrmSession, integration_id: uuid.UUID, authorization: str | None) -> Integration:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError("authentication_required", "A bearer ingress token is required.", 401)
    token = authorization.split(" ", 1)[1].strip()
    token_hash = hash_token(token)
    i = db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.ingest_token_hash.isnot(None),
        )
    ).scalar_one_or_none()
    if i is None or i.ingest_token_hash is None:
        raise ApiError("resource_not_found", "Unknown or disabled integration.", 404)
    if not constant_time_eq_bytes(i.ingest_token_hash, token_hash):
        raise ApiError("authentication_required", "The ingress token is invalid.", 401)
    if i.deleted_at is not None or not i.enabled:
        raise ApiError("resource_not_found", "Unknown or disabled integration.", 404)
    return i


@router.post("/{integration_id}/n8n")
async def ingest_n8n(
    integration_id: uuid.UUID,
    request: Request,
    db: OrmSession = Depends(get_db_session),
) -> dict:
    integration = _authenticate_integration(
        db, integration_id, request.headers.get("authorization")
    )
    ok, retry_after = allow(
        f"ingest:{integration.id}", limit=config.settings.ingest_rate_per_minute, window_seconds=60
    )
    if not ok:
        raise ApiError("rate_limited", "Ingestion rate limit reached.", 429, headers={"Retry-After": str(retry_after)})

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise ApiError("unsupported_media_type", "Only application/json is accepted.", 415)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > config.settings.max_inbound_payload_bytes:
            raise ApiError("payload_too_large", "The payload exceeds the size limit.", 413)
    body = bytes(body)

    import json

    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError("validation_error", "The payload is not valid JSON.", 422)
    if not isinstance(payload, dict):
        raise ApiError("validation_error", "The payload must be a JSON object.", 422)

    adapter = get_adapter("n8n")
    workflow_identity, event = adapter.parse_error_webhook_payload(payload)
    if not workflow_identity:
        raise ApiError("validation_error", "An n8n workflow id is required.", 422)

    event_type = event["event_type"]
    execution_external_id = event.get("execution_external_id")
    error_obj = event.get("error") or {}
    error_message = (
        error_obj.get("message") if isinstance(error_obj, dict) else error_obj
    )
    started_epoch = None
    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else None
    if execution and execution.get("startedAt") is not None:
        started_epoch = str(execution.get("startedAt"))
    dedupe_key = compute_event_dedupe_key(
        str(integration.id),
        workflow_identity["external_id"] if workflow_identity else None,
        execution_external_id,
        str(error_message) if error_message else None,
        started_epoch,
    )

    redacted_payload = redact_value(payload)

    event_row = InboundEvent(
        workspace_id=integration.workspace_id,
        integration_id=integration.id,
        source_event_key=dedupe_key,
        event_type=event_type,
        source_execution_id=execution_external_id,
        payload_redacted=redacted_payload,
        payload_hash=payload_hash(body),
        received_at=utcnow(),
        processing_status="pending",
        processing_attempts=0,
    )
    db.add(event_row)
    try:
        db.flush()
    except IntegrityError:
        # Duplicate delivery — return the original event id (API_SPEC 8.1).
        db.rollback()
        existing = db.execute(
            select(InboundEvent).where(
                InboundEvent.integration_id == integration.id,
                InboundEvent.source_event_key == dedupe_key,
            )
        ).scalar_one()
        return {
            "data": {"event_id": str(existing.id), "status": "accepted", "duplicate": True},
            "meta": {"request_id": request.state.request_id},
        }

    outbox = OutboxMessage(
        workspace_id=integration.workspace_id,
        aggregate_type="inbound_event",
        aggregate_id=event_row.id,
        message_type="process_event",
        payload={"event_id": str(event_row.id)},
        available_at=utcnow(),
    )
    db.add(outbox)
    if not integration.credential_ciphertext:
        integration.status = "healthy"
        integration.last_successful_check_at = utcnow()
    db.commit()  # commit before acknowledging (PRD: persist before success)

    return {
        "data": {"event_id": str(event_row.id), "status": "accepted", "duplicate": False},
        "meta": {"request_id": request.state.request_id},
    }


@router.post("/{integration_id}/generic")
async def ingest_generic(
    integration_id: uuid.UUID,
    request: Request,
    db: OrmSession = Depends(get_db_session),
) -> dict:
    raise ApiError(
        "capability_not_supported",
        "Only the n8n adapter is available in this release.",
        409,
    )


def _bounded_json(value: Any, max_bytes: int) -> bytes:
    import json

    data = json.dumps(value, default=str).encode("utf-8")
    return data[:max_bytes]
