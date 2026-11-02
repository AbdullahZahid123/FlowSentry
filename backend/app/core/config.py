"""FlowSentry application configuration.

All runtime configuration is sourced from environment variables (or a local
`.env` file during development) — never from code, and never with default
production credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application -------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "FlowSentry"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"

    # --- security ----------------------------------------------------------
    app_secret_key: str = Field(default="", description="Secret used to sign cursors and one-time links.")
    encryption_key: str = Field(default="", description="Base64 or hex 32-byte AES-256-GCM key for credentials at rest.")
    encryption_key_version: str = "v1"
    session_cookie_name: str = "flowsentry_session"
    csrf_cookie_name: str = "flowsentry_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_lifetime_seconds: int = 60 * 60 * 24 * 14
    session_cookie_secure: bool = False
    registration_mode: Literal["setup", "invite", "open", "closed"] = "invite"
    max_inbound_payload_bytes: int = 256 * 1024

    # --- database ----------------------------------------------------------
    database_url: str = "postgresql://postgres@127.0.0.1:54321/flowsentry"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- workers -----------------------------------------------------------
    worker_enabled: bool = True
    worker_interval_seconds: float = 1.0
    worker_batch_size: int = 20
    worker_max_attempts: int = 8
    worker_job_timeout_seconds: int = 120
    worker_embedded: bool = True

    # --- integration defaults ---------------------------------------------
    default_poll_interval_seconds: int = 60
    min_poll_interval_seconds: int = 15
    max_poll_interval_seconds: int = 86400
    poll_page_size: int = Field(default=20, ge=1, le=100)
    ingest_rate_per_minute: int = 600

    # --- incident engine ---------------------------------------------------
    grouping_window_seconds: int = 3600
    reopen_window_seconds: int = 1800
    severity_window_seconds: int = 3600

    # --- notifications -----------------------------------------------------
    notification_max_attempts: int = 5
    notification_backoff_seconds: list[int] = [60, 300, 900, 3600, 3600]
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "flowsentry@localhost"
    smtp_use_tls: bool = True
    telegram_bot_token: str = ""
    http_outbound_timeout_seconds: float = 10.0
    http_outbound_max_bytes: int = 2 * 1024 * 1024
    allow_private_network: bool = False

    # --- retention defaults (seconds until purge) ---------------------------
    retention_event_payload_seconds: int = Field(default=30 * 86400, ge=86400)
    retention_execution_seconds: int = Field(default=90 * 86400, ge=86400)

    # --- optional AI (advisory only; core never requires it) ---------------
    ai_enabled: bool = False
    ai_provider: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    ai_base_url: Optional[str] = None

    @model_validator(mode="after")
    def validate_production(self):
        if self.app_env == "production":
            if len(self.app_secret_key) < 32 or not self.encryption_key:
                raise ValueError("Production requires APP_SECRET_KEY (32+ characters) and ENCRYPTION_KEY.")
            import base64
            try:
                key = bytes.fromhex(self.encryption_key)
            except ValueError:
                try:
                    key = base64.b64decode(self.encryption_key, validate=True)
                except Exception:
                    key = b""
            if len(key) != 32 or "change-me" in self.app_secret_key.lower():
                raise ValueError("Production requires a valid 32-byte encryption key and a generated signing secret.")
            if not self.session_cookie_secure or not self.frontend_url.startswith("https://"):
                raise ValueError("Production requires secure session cookies and an HTTPS FRONTEND_URL.")
        return self

    @property
    def cors_origins(self) -> list[str]:
        base = {self.frontend_url.rstrip("/"), f"http://localhost:{self.api_port}"}
        if self.app_env == "development":
            base |= {
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3001",
            }
        return sorted(base)


settings = Settings()
