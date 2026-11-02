"""n8n adapter implementation.

Boundaries honored from ARCHITECTURE.md section 7 and ADR-004:
- Uses documented public API operations only (API key header, cursor
  pagination).
- Native retry/replay is NOT assumed: capabilities declare
  retry_execution=False until a documented supported operation is verified
  for the connected version.
- Both error-workflow webhook payload shapes are handled: standard
  execution failures and trigger-activation failures (no execution id).
"""

from __future__ import annotations

import re
from urllib.parse import urlencode, quote
from datetime import datetime, timezone
from typing import Any

import httpx

from app.adapters.base import (
    AdapterError,
    Capabilities,
    NormalizedExecution,
    NormalizedPage,
    NormalizedWorkflow,
)
from app.core import config, egress
from app.core.redaction import redact_string, redact_value

AUTH_HEADER = "X-N8N-API-KEY"


def node_name(value: Any) -> str | None:
    """n8n errors can contain the complete node object. Keep only its name."""
    if isinstance(value, dict):
        value = value.get("name")
    return redact_string(value)[:256] if isinstance(value, str) and value else None

_STATUS_MAP = {
    "success": "success",
    "error": "failed",
    "failed": "failed",
    "crashed": "failed",
    "running": "running",
    "new": "running",
    "waiting": "waiting",
    "canceled": "canceled",
    "cancelled": "canceled",
    "unknown": "unknown",
}

_ENV_HINTS = {
    "prod": "production",
    "production": "production",
    "staging": "staging",
    "stage": "staging",
    "test": "staging",
    "dev": "development",
    "development": "development",
}


class N8nAdapter:
    provider_name = "n8n"
    capabilities = Capabilities(
        workflow_list=True,
        execution_list=True,
        execution_detail=True,
        retry_execution=False,  # not assumed without documented API verification
    )

    # -- helpers ------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(trust_env=False, timeout=config.settings.http_outbound_timeout_seconds)

    def _request(
        self,
        method: str,
        url: str,
        credential: str | None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {"Accept": "application/json"}
        if credential:
            headers[AUTH_HEADER] = credential
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        try:
            resp = egress.safe_request(
                method, url, headers=headers, json_body=json_body, timeout=15.0
            )
        except egress.SsrfViolation as e:
            raise AdapterError("ssrf_violation", str(e)) from e
        except httpx.HTTPError as e:
            raise AdapterError("integration_unavailable", f"Source request failed: {e.__class__.__name__}") from e
        if resp.status_code == 401 or resp.status_code == 403:
            raise AdapterError("integration_auth_failed", "Source rejected the credentials.", resp.status_code)
        if resp.status_code == 429:
            raise AdapterError("rate_limited", "Source rate limit reached.", 429)
        if resp.status_code >= 500:
            raise AdapterError("integration_unavailable", "Source returned a server error.", resp.status_code)
        if resp.status_code >= 400:
            raise AdapterError("validation_error", "Source rejected the request.", resp.status_code)
        try:
            return resp.json()
        except ValueError as e:
            raise AdapterError("validation_error", "Source returned a non-JSON body.") from e

    # -- capabilities ---------------------------------------------------------

    def test_connection(self, base_url: str, credential: str) -> dict[str, Any]:
        base = base_url.rstrip("/")
        data = self._request("GET", f"{base}/api/v1/workflows?limit=1", credential)
        workflows = data.get("data") if isinstance(data, dict) else None
        version = None  # No undocumented provider endpoints are queried.
        if not isinstance(workflows, list):
            raise AdapterError("validation_error", "Source did not return a workflow list.")
        return {
            "ok": True,
            "provider": self.provider_name,
            "workflows_visible": isinstance(workflows, list),
            "version_hint": version,
        }

    # -- discovery ------------------------------------------------------------

    def list_workflows(
        self, base_url: str, credential: str, cursor: str | None, limit: int
    ) -> NormalizedPage:
        base = base_url.rstrip("/")
        params: dict[str, Any] = {"limit": limit, "excludePinnedData": "true"}
        if cursor:
            params["cursor"] = cursor
        data = self._request("GET", f"{base}/api/v1/workflows", credential, params=params)
        items = self._parse_page(data).items
        normalized = [self._normalize_workflow(w) for w in items if isinstance(w, dict)]
        page = self._parse_page(data)
        return NormalizedPage(items=normalized, next_cursor=page.next_cursor)

    def _normalize_workflow(self, raw: dict[str, Any]) -> NormalizedWorkflow:
        external_id = str(raw.get("id", "") or "")
        name = str(raw.get("name") or f"Workflow {external_id}")
        environment = self._infer_environment(raw)
        meta = {
            k: raw.get(k)
            for k in ("active", "createdAt", "updatedAt", "tags", "versionId")
            if raw.get(k) is not None
        }
        from app.modules.workflow_logic import extract_topology
        topology = extract_topology(raw)
        if topology is not None:
            meta["topology"] = topology
        desc = raw.get("note") or raw.get("description")
        return NormalizedWorkflow(
            external_id=external_id,
            name=name,
            description=desc if isinstance(desc, str) else None,
            is_active=bool(raw.get("active")) if raw.get("active") is not None else None,
            environment=environment,
            provider_metadata=meta,
        )

    def _infer_environment(self, raw: dict[str, Any]) -> str:
        hay = " ".join(
            str(raw.get(k, "")) for k in ("name", "note", "description")
        ).lower()
        for token, env in _ENV_HINTS.items():
            if token in hay:
                return env
        return "unknown"

    # -- executions ------------------------------------------------------------

    def list_executions(
        self,
        base_url: str,
        credential: str,
        cursor: str | None,
        limit: int,
        resource_external_id: str | None = None,
    ) -> NormalizedPage:
        base = base_url.rstrip("/")
        # n8n omits resultData (including error/node) unless explicitly requested.
        # Only normalized, redacted metadata is retained from these bounded pages.
        params: dict[str, Any] = {"limit": limit, "includeData": "true"}
        if resource_external_id:
            params["workflowId"] = resource_external_id
        if cursor:
            params["cursor"] = cursor
        data = self._request("GET", f"{base}/api/v1/executions", credential, params=params)
        page = self._parse_page(data)
        normalized = [self.normalize_execution_payload(e) for e in page.items if isinstance(e, dict)]
        return NormalizedPage(items=normalized, next_cursor=page.next_cursor)

    def get_execution(
        self, base_url: str, credential: str, execution_external_id: str
    ) -> NormalizedExecution | None:
        base = base_url.rstrip("/")
        data = self._request("GET", f"{base}/api/v1/executions/{quote(execution_external_id, safe='')}", credential,
                             params={"includeData": "true"})
        if not isinstance(data, dict):
            return None
        return self.normalize_execution_payload(data)

    def _parse_page(self, data: Any) -> NormalizedPage:
        if not isinstance(data, dict):
            raise AdapterError("validation_error", "Unexpected source response shape.")
        items = data.get("data") or data.get("results") or []
        if not isinstance(items, list):
            raise AdapterError("validation_error", "Unexpected source response shape.")
        next_cursor = data.get("nextCursor")
        if next_cursor in ("", 0):
            next_cursor = None
        return NormalizedPage(items=items, next_cursor=next_cursor if isinstance(next_cursor, str) else None)

    def normalize_execution_payload(self, raw: dict[str, Any]) -> NormalizedExecution:
        ext_id = raw.get("id")
        external_id = str(ext_id) if ext_id is not None else None
        status_raw = str(raw.get("status") or "unknown").lower()
        status = _STATUS_MAP.get(status_raw, "unknown")
        started = self._parse_dt(raw.get("startedAt"))
        stopped = self._parse_dt(raw.get("stoppedAt"))
        duration_ms = None
        if started and stopped:
            duration_ms = max(0, int((stopped - started).total_seconds() * 1000))
        result = raw.get("data", {}).get("resultData", {}) if isinstance(raw.get("data"), dict) else {}
        err = raw.get("error") if isinstance(raw.get("error"), dict) else result.get("error")
        err = err if isinstance(err, dict) else None
        error_message = (
            str(err.get("message")) if err and err.get("message") is not None else None
        )
        failed_node = node_name(err.get("node")) if err else None
        failed_node = failed_node or node_name(result.get("lastNodeExecuted"))
        metadata = {
            k: raw.get(k)
            for k in ("mode", "workflowId", "retryOf", "retrySuccessId")
            if raw.get(k) is not None
        }
        source_url = None
        return NormalizedExecution(
            external_id=external_id,
            status=status,
            started_at=started,
            finished_at=stopped,
            duration_ms=duration_ms,
            failed_node=failed_node,
            error_class=str(err.get("name")) if err and err.get("name") else None,
            error_code=str(err.get("httpCode") or err.get("code"))[:80] if err and (err.get("httpCode") or err.get("code")) else None,
            error_message_redacted=redact_string(error_message) if error_message else None,
            source_url=source_url,
            source_retry_of=str(raw.get("retryOf")) if raw.get("retryOf") else None,
            mode=str(raw.get("mode")) if raw.get("mode") else None,
            provider_metadata=redact_value(metadata),
        )

    def _parse_dt(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        text = str(value)
        try:
            normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    # -- webhook payload parsing ------------------------------------------------

    def parse_error_webhook_payload(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return (workflow_identity|None, event_payload).

        Handles:
        - standard execution failure payloads (execution.id present)
        - trigger activation failure payloads (different shape, no execution)
        """
        workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else None
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else None
        trigger = payload.get("trigger") if isinstance(payload.get("trigger"), dict) else None
        err = next(
            (
                candidate
                for candidate in (
                    payload.get("error"),
                    (execution or {}).get("error"),
                    (trigger or {}).get("error"),
                )
                if isinstance(candidate, dict)
            ),
            None,
        )

        event: dict[str, Any] = {
            "event_type": "execution.failed" if execution else "trigger.failed",
            "execution_external_id": (
                str(execution.get("id")) if execution and execution.get("id") is not None else None
            ),
            "execution_url": execution.get("url") if execution else None,
            "retry_of": execution.get("retryOf") if execution else None,
            "last_node_executed": node_name((execution or {}).get("lastNodeExecuted")) or node_name((err or {}).get("node")) or node_name((trigger or {}).get("node")),
            "mode": (execution or {}).get("mode"),
            "error": (
                err
                if err is not None
                else (
                    payload.get("message") if payload.get("message") is not None
                    else (execution or {}).get("error")
                )
            ),
        }
        if workflow and workflow.get("id") is not None:
            wf = {
                "external_id": str(workflow.get("id")),
                "name": str(workflow.get("name") or f"Workflow {workflow.get('id')}"),
            }
            return wf, event
        return None, event


adapter_registry: dict[str, Any] = {}


def register_adapters() -> dict[str, N8nAdapter]:
    adapter_registry["n8n"] = N8nAdapter()
    return adapter_registry


def get_adapter(provider: str) -> N8nAdapter | None:
    if not adapter_registry:
        register_adapters()
    return adapter_registry.get(provider)
