"""Error fingerprinting (PRD section 14.1, ARCHITECTURE.md section 10.1).

Fingerprints are stable grouping keys derived from identity fields — never
from execution IDs or timestamps. Versioned so grouping policy can evolve.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core import redaction

FINGERPRINT_VERSION = 1


@dataclass(frozen=True)
class FingerprintInput:
    workspace_id: str | None
    integration_id: str | None
    workflow_external_id: str | None
    error_class: str | None
    failed_node: str | None
    error_message: str | None


def normalize_error_class(error_class: str | None) -> str:
    if not error_class:
        return "unknown"
    value = error_class.strip().lower()
    value = value.replace(" ", "_").replace("::", "_").replace(".", "_")
    value = redaction.normalize_text_for_fingerprint(value).replace(" ", "_")
    return value or "unknown"


def normalize_node(node: str | None) -> str:
    if not node:
        return "unknown"
    return redaction.normalize_text_for_fingerprint(node)[:120] or "unknown"


def compute_error_class(message_hash: str) -> str:
    return message_hash


def error_class_key(message: str | None) -> str:
    """Map common provider error text into a small, stable class name."""
    if not message:
        return "unknown"
    m = message.lower()
    if "rate limit" in m or "too many requests" in m or " http 429" in m or "429" in m:
        return "api_rate_limit"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "unauthorized" in m or "401" in m or "invalid api key" in m or "auth" in m and "fail" in m:
        return "auth_failure"
    if "not found" in m or "404" in m:
        return "not_found"
    if "refused" in m or "connect" in m and "unreachable" in m:
        return "connection_unreachable"
    if "ssl" in m or "certificate" in m or "https" in m and "handshak" in m:
        return "tls_error"
    if " 5" in m or "502" in m or "503" in m or "504" in m:
        return "upstream_5xx"
    if "passed" in m and "expiration" in m:
        return "expired"
    return "node_error"


def compute_fingerprint(inp: FingerprintInput) -> tuple[str, str, str, str]:
    """Return (fingerprint, message_template, error_class, node_norm)."""
    template = redaction.error_message_template(inp.error_message)
    error_class = normalize_error_class(inp.error_class) if inp.error_class else error_class_key(inp.error_message)
    node_norm = normalize_node(inp.failed_node)
    parts = [
        inp.workspace_id or "",
        inp.integration_id or "",
        inp.workflow_external_id or "",
        error_class,
        node_norm,
        template,
    ]
    canonical = "\x1f".join(parts)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return fingerprint, template, error_class, node_norm


def compute_event_dedupe_key(
    integration_id: str,
    workflow_external_id: str | None,
    execution_external_id: str | None,
    error_message: str | None,
    started_at_epoch: str | None,
) -> str:
    """Stable key for at-least-once delivery dedup (priority order per ARCH 9.2).

    1. Provider execution ID + event type (executions are unique per workflow).
    2. Deterministic digest of identity fields otherwise.
    """
    if execution_external_id:
        return f"exe:{integration_id}:{workflow_external_id or ''}:{execution_external_id}"
    digest = hashlib.sha256(
        "\x1f".join(
            [
                integration_id,
                workflow_external_id or "",
                redaction.normalize_text_for_fingerprint(error_message or ""),
                started_at_epoch or "",
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"dig:{digest}"
