"""Domain schemas (Pydantic v2) shared across modules."""

from __future__ import annotations

from typing import Any, Optional, Annotated

from pydantic import BaseModel, EmailStr, Field, AfterValidator


def validate_timezone(value:str)->str:
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError,ValueError):
        raise ValueError("Choose a valid IANA timezone.")
    return value
Timezone=Annotated[str,AfterValidator(validate_timezone)]


class Envelope(BaseModel):
    data: Any
    meta: dict[str, Any] = {"request_id": None}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


class SetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    workspace_name: str = Field(min_length=1, max_length=120)
    timezone: Timezone = "UTC"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: Timezone = "UTC"


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: Timezone | None = None


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|operator|viewer)$")


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern="^(owner|admin|operator|viewer)$")


class IntegrationCreate(BaseModel):
    provider: str = Field(default="n8n", pattern="^[a-z0-9_]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    base_url: str | None = None
    api_key: str | None = None
    poll_interval_seconds: int = Field(default=60, ge=15, le=86400)


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = None
    api_key: str | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=15, le=86400)
    enabled: bool | None = None


class WorkflowUpdate(BaseModel):
    monitoring_enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=250)
    environment: str | None = Field(default=None, pattern="^(production|staging|development|unknown)$")
    criticality: str | None = Field(default=None, pattern="^(critical|high|normal|low)$")
    expected_interval_seconds: int | None = Field(default=None, ge=30, le=31536000)


class IncidentUpdate(BaseModel):
    severity: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    status: str | None = Field(
        default=None,
        pattern="^(open|acknowledged|investigating|recovering|resolved|suppressed)$",
    )
    assigned_to: str | None = None


class ResolveRequest(BaseModel):
    resolution_note: str | None = Field(default=None, max_length=4000)


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    is_internal: bool = True


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    enabled: bool = True
    event_types: list[str] = Field(min_length=1)
    conditions: dict[str, Any] | None = None
    severity_minimum: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    channel_ids: list[str] = Field(default_factory=list)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    enabled: bool | None = None
    event_types: list[str] | None = None
    conditions: dict[str, Any] | None = None
    severity_minimum: str | None = Field(default=None, pattern="^(critical|high|medium|low)$")
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    channel_ids: list[str] | None = None


class ChannelCreate(BaseModel):
    channel_type: str = Field(pattern="^(email|telegram|webhook|log)$")
    name: str = Field(min_length=1, max_length=120)
    configuration: dict[str, Any]
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    configuration: dict[str, Any] | None = None
    enabled: bool | None = None


class RetryRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    mode: str = "provider_supported_retry"
    acknowledge_side_effect_risk: bool = False
    reason: str | None = Field(default=None, max_length=1000)
