"""Shared cursor pagination helpers (API_SPECIFICATION.md section 4).

Cursors are integrity-protected via HMAC to prevent filter-context abuse.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any
from datetime import datetime
import uuid

from app.core import config
from app.core.errors import ApiError


def _sign(payload: str) -> str:
    key = (config.settings.app_secret_key or "flowsentry-dev-secret").encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:16]


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    b = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{b}.{_sign(b)}"


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    b, _, sig = cursor.partition(".")
    if len(cursor) > 2048 or not hmac.compare_digest(_sign(b), sig):
        raise ApiError("validation_error", "Invalid pagination cursor.", 422)
    try:
        pad = "=" * (-len(b) % 4)
        raw = base64.urlsafe_b64decode(b + pad)
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise ValueError("cursor must be an object")
        for key in ("id", "k"):
            if key in values:
                uuid.UUID(values[key])
        for key in ("created_at", "s"):
            if values.get(key) is not None:
                values[key] = datetime.fromisoformat(values[key])
                if values[key].tzinfo is None:
                    raise ValueError("cursor timestamp must include a timezone")
        return values
    except Exception as exc:
        raise ApiError("validation_error", "Invalid pagination cursor.", 422) from exc


def page_meta(request_id: str | None, next_values: dict[str, Any] | None, has_more: bool) -> dict:
    return {
        "request_id": request_id,
        "next_cursor": encode_cursor(next_values) if has_more and next_values else None,
        "has_more": has_more,
    }
