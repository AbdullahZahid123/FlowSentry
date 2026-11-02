"""Provider-neutral adapter interface.

ARCHITECTURE.md section 6.3: the core application must not depend on
provider-specific payload shapes. An adapter declares capabilities and must
never assume an operation the provider has not documented for its version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Capabilities:
    workflow_list: bool = False
    execution_list: bool = False
    execution_detail: bool = False
    retry_execution: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {
            "workflow_list": self.workflow_list,
            "execution_list": self.execution_list,
            "execution_detail": self.execution_detail,
            "retry_execution": self.retry_execution,
        }


@dataclass(frozen=True)
class AdapterError(Exception):
    code: str
    message: str
    http_status: int | None = None

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"{self.code}: {self.message}"


@dataclass
class NormalizedWorkflow:
    external_id: str
    name: str
    description: str | None = None
    is_active: bool | None = None
    environment: str = "unknown"
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedExecution:
    external_id: str | None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    failed_node: str | None = None
    error_class: str | None = None
    error_code: str | None = None
    error_message_redacted: str | None = None
    source_url: str | None = None
    source_retry_of: str | None = None
    mode: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedPage:
    items: list[Any]
    next_cursor: str | None = None


@runtime_checkable
class AutomationAdapter(Protocol):
    """Provider adapter contract."""

    provider_name: str
    capabilities: Capabilities

    def test_connection(
        self, base_url: str, credential: str
    ) -> dict[str, Any]:
        """Validate connectivity + credentials. Never returns raw bodies."""
        ...

    def list_workflows(
        self, base_url: str, credential: str, cursor: str | None, limit: int
    ) -> NormalizedPage:
        ...

    def list_executions(
        self,
        base_url: str,
        credential: str,
        cursor: str | None,
        limit: int,
        resource_external_id: str | None = None,
    ) -> NormalizedPage:
        ...

    def get_execution(
        self, base_url: str, credential: str, execution_external_id: str
    ) -> NormalizedExecution | None:
        ...

    def normalize_execution_payload(self, raw: dict[str, Any]) -> NormalizedExecution:
        ...

    def parse_error_webhook_payload(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return (workflow_identity, execution_or_event) tuples for ingestion."""
        ...
