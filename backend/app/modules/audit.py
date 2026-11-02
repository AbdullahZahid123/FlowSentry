"""Append-only audit logging (M2-09). Audit records are never updated or
deleted through normal application paths (DATABASE.md section 11)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.models.models import AuditLog


def record_audit(
    db: OrmSession,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None = None,
    actor_type: str = "user",
    actor_id: uuid.UUID | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    ip_hash = (
        hashlib.sha256(ip.encode("utf-8")).digest()[:16] if ip else None
    )
    entry = AuditLog(
        workspace_id=workspace_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        ip_hash=ip_hash,
        metadata=metadata or {},
        created_at=utcnow(),
    )
    db.add(entry)
