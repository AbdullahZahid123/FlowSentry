"""Integration management: connect n8n instances, credential encryption,
ingress tokens, connectivity tests, workflow sync (API_SPEC section 7)."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.adapters.n8n.adapter import get_adapter
from app.core import config
from app.core.db import utcnow
from app.core.egress import validate_outbound_url
from app.core.errors import ApiError
from app.core.security import decrypt_secret, encrypt_secret, hash_token
from app.deps import check_csrf, get_db_session, get_membership, require_role
from app.models.models import Integration, SyncCursor, Workflow, WorkspaceMember
from app.modules import audit
from app.schemas.common import IntegrationCreate, IntegrationUpdate

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _integration_payload(i: Integration, ingress_token_once: str | None = None) -> dict:
    data = {
        "id": str(i.id),
        "provider": i.provider,
        "name": i.name,
        "base_url": i.base_url,
        "status": i.status,
        "capabilities": i.capabilities or {},
        "poll_interval_seconds": i.poll_interval_seconds,
        "enabled": i.enabled,
        "webhook_only": i.base_url is None,
        "last_successful_check_at": i.last_successful_check_at.isoformat() if i.last_successful_check_at else None,
        "last_error_code": i.last_error_code,
        "last_error_at": i.last_error_at.isoformat() if i.last_error_at else None,
        "created_at": i.created_at.isoformat(),
    }
    if ingress_token_once is not None:
        data["ingress_token_once"] = ingress_token_once
        data["ingest_url_template"] = f"/ingest/{i.id}/n8n"
    return data


def _generate_capabilities(provider: str, has_api_key: bool) -> dict:
    adapter = get_adapter(provider)
    if adapter is None:
        return {"workflow_list": False, "execution_list": False, "execution_detail": False, "retry_execution": False}
    caps = adapter.capabilities.as_dict()
    if not has_api_key:
        # Webhook-only connections cannot poll; polling capabilities stay false.
        caps = {k: False for k in caps}
    return caps


@router.get("")
def list_integrations(
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    rows = (
        db.execute(
            select(Integration)
            .where(
                Integration.workspace_id == member.workspace_id,
                Integration.deleted_at.is_(None),
            )
            .order_by(Integration.created_at)
        )
        .scalars()
        .all()
    )
    return {
        "data": [_integration_payload(i) for i in rows],
        "meta": {"request_id": None, "next_cursor": None, "has_more": False},
    }


@router.post("", status_code=201)
def create_integration(
    payload: IntegrationCreate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    if payload.provider != "n8n":
        raise ApiError("validation_error", "This provider is not supported yet.", 422)

    base_url = None
    if payload.base_url:
        if not payload.api_key:
            raise ApiError(
                "validation_error",
                "An API key is required when a base URL is provided.",
                422,
            )
        base_url = validate_outbound_url(payload.base_url)

    credential_ciphertext = None
    credential_key_version = None
    if payload.api_key:
        credential_ciphertext, credential_key_version = encrypt_secret(payload.api_key)

    ingress_token = secrets.token_urlsafe(32)
    integration = Integration(
        workspace_id=member.workspace_id,
        provider=payload.provider,
        name=payload.name,
        base_url=base_url,
        credential_ciphertext=credential_ciphertext,
        credential_key_version=credential_key_version,
        ingest_token_hash=hash_token(ingress_token),
        status="pending",
        capabilities=_generate_capabilities(payload.provider, bool(payload.api_key)),
        poll_interval_seconds=payload.poll_interval_seconds,
        enabled=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(integration)
    db.flush()

    if base_url:
        for resource in ("workflows", "executions"):
            db.add(
                SyncCursor(
                    integration_id=integration.id,
                    resource_type=resource,
                    next_poll_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
    audit.record_audit(
        db,
        action="integration.created",
        resource_type="integration",
        resource_id=integration.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"provider": payload.provider},
    )
    db.commit()
    return {
        "data": _integration_payload(integration, ingress_token_once=ingress_token),
        "meta": {"request_id": request.state.request_id},
    }


def _load_integration(db: OrmSession, integration_id: uuid.UUID, workspace_id: uuid.UUID) -> Integration:
    i = db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.workspace_id == workspace_id,
            Integration.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if i is None:
        raise ApiError("resource_not_found", "Integration not found.", 404)
    return i


@router.get("/{integration_id}")
def get_integration(
    integration_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    return {"data": _integration_payload(_load_integration(db, integration_id, member.workspace_id)), "meta": {"request_id": None}}


@router.post("/{integration_id}/test")
def test_integration(
    integration_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_integration(db, integration_id, member.workspace_id)
    adapter = get_adapter(i.provider)
    if adapter is None or not i.base_url or not i.credential_ciphertext:
        raise ApiError(
            "capability_not_supported",
            "This integration is webhook-only; add a base URL and API key to test connectivity.",
            409,
        )
    credential = decrypt_secret(i.credential_ciphertext)
    try:
        result = adapter.test_connection(i.base_url, credential)
        i.status = "healthy"
        i.last_successful_check_at = utcnow()
        i.last_error_code = None
        result["connection"] = "ok"
    except Exception as e:  # AdapterError and unexpected failures both map here
        from app.adapters.base import AdapterError

        code = e.code if isinstance(e, AdapterError) else "integration_unavailable"
        i.status = "error" if code == "integration_auth_failed" else "degraded"
        i.last_error_code = code
        i.last_error_at = utcnow()
        result = {"connection": "failed", "error_code": code}
    i.updated_at = utcnow()
    db.add(i)
    audit.record_audit(
        db,
        action="integration.tested",
        resource_type="integration",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"result_status": i.status},
    )
    db.commit()
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.post("/{integration_id}/sync", status_code=202)
def trigger_sync(
    integration_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("operator")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_integration(db, integration_id, member.workspace_id)
    if not i.enabled:
        raise ApiError("conflict", "This integration is disabled.", 409)
    if not i.base_url or not i.credential_ciphertext:
        raise ApiError(
            "capability_not_supported",
            "Workflow synchronization requires a connected API credential.",
            409,
        )
    cursor = db.execute(
        select(SyncCursor).where(
            SyncCursor.integration_id == i.id, SyncCursor.resource_type == "workflows"
        )
    ).scalar_one_or_none()
    if cursor is not None:
        cursor.next_poll_at = utcnow()
        cursor.updated_at = utcnow()
        db.add(cursor)
    db.commit()
    return {
        "data": {
            "job_id": str(i.id),
            "status": "queued",
            "message": "Workflow synchronization has been queued.",
        },
        "meta": {"request_id": request.state.request_id},
    }


@router.get("/{integration_id}/health")
def integration_health(
    integration_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_integration(db, integration_id, member.workspace_id)
    cursors = (
        db.execute(select(SyncCursor).where(SyncCursor.integration_id == i.id)).scalars().all()
    )
    poll_status = [
        {
            "resource_type": c.resource_type,
            "last_success_at": c.last_success_at.isoformat() if c.last_success_at else None,
            "next_poll_at": c.next_poll_at.isoformat() if c.next_poll_at else None,
            "last_error": c.last_error,
        }
        for c in cursors
    ]
    return {
        "data": {
            "status": i.status,
            "last_successful_check_at": i.last_successful_check_at.isoformat() if i.last_successful_check_at else None,
            "last_error_code": i.last_error_code,
            "last_error_at": i.last_error_at.isoformat() if i.last_error_at else None,
            "polling": poll_status,
            "capabilities": i.capabilities or {},
        },
        "meta": {"request_id": None},
    }


@router.patch("/{integration_id}")
def update_integration(
    integration_id: uuid.UUID,
    payload: IntegrationUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_integration(db, integration_id, member.workspace_id)
    if payload.name is not None:
        i.name = payload.name
    if payload.enabled is not None:
        i.enabled = payload.enabled
    if payload.poll_interval_seconds is not None:
        i.poll_interval_seconds = payload.poll_interval_seconds
    if payload.base_url is not None:
        i.base_url = validate_outbound_url(payload.base_url)
    if payload.api_key:
        ct, ver = encrypt_secret(payload.api_key)
        i.credential_ciphertext = ct
        i.credential_key_version = ver
        i.capabilities = _generate_capabilities(i.provider, True)
        i.status = "pending"
    i.updated_at = utcnow()
    db.add(i)
    audit.record_audit(
        db,
        action="integration.updated",
        resource_type="integration",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _integration_payload(i), "meta": {"request_id": request.state.request_id}}


@router.post("/{integration_id}/rotate-ingress-token")
def rotate_ingress_token(
    integration_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    i = _load_integration(db, integration_id, member.workspace_id)
    token = secrets.token_urlsafe(32)
    i.ingest_token_hash = hash_token(token)
    i.updated_at = utcnow()
    db.add(i)
    audit.record_audit(
        db,
        action="integration.ingress_token_rotated",
        resource_type="integration",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {
        "data": {"ingress_token_once": token},
        "meta": {"request_id": request.state.request_id},
    }


@router.delete("/{integration_id}", status_code=204)
def delete_integration(
    integration_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> None:
    i = _load_integration(db, integration_id, member.workspace_id)
    # Disable first; history is preserved per retention policy (API_SPEC 7.8).
    i.enabled = False
    i.deleted_at = utcnow()
    i.updated_at = utcnow()
    db.add(i)
    audit.record_audit(
        db,
        action="integration.deleted",
        resource_type="integration",
        resource_id=i.id,
        workspace_id=member.workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return Response(status_code=204)
