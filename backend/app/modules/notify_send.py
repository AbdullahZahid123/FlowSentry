"""Outbound notification senders (API_SPECIFICATION.md section 12.3).

Pure send functions: no database access, no retries (the worker owns retry
policy and backoff). Each sender returns (ok, error_code_or_message) instead
of raising, so delivery results map cleanly onto NotificationAttempt rows.
"""

from __future__ import annotations

import logging
import smtplib
from typing import Any
from email.message import EmailMessage

from app.core import config
from app.core.egress import safe_request, validate_webhook_destination

logger = logging.getLogger("flowsentry.notify")

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_notification_payload(
    channel_type: str,
    config_map: dict[str, Any],
    subject: str,
    body: str,
) -> tuple[bool, str | None]:
    """Dispatch to the channel-specific sender. Never raises."""
    try:
        if channel_type == "email":
            return _send_email(config_map, subject, body)
        if channel_type == "telegram":
            return _send_telegram(config_map, subject, body)
        if channel_type == "webhook":
            return _send_webhook(config_map, subject, body)
        if channel_type == "log":
            logger.info("notification | %s | %s", subject, body[:2000])
            return True, None
        return False, "unsupported_channel_type"
    except Exception as e:  # unexpected transport failures degrade to a result
        logger.warning("notification send failed for %s: %s", channel_type, type(e).__name__)
        return False, "delivery_failed"


def _send_email(cfg: dict[str, Any], subject: str, body: str) -> tuple[bool, str | None]:
    settings = config.settings
    if not settings.smtp_host:
        return False, "smtp_not_configured"
    to = str(cfg.get("to") or "").strip()
    if not to or "@" not in to:
        return False, "invalid_recipient"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(body)

    if settings.smtp_use_tls and settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    return True, None


def _send_telegram(cfg: dict[str, Any], subject: str, body: str) -> tuple[bool, str | None]:
    token = config.settings.telegram_bot_token
    if not token:
        return False, "telegram_not_configured"
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not chat_id:
        return False, "invalid_recipient"

    text = f"{subject}\n\n{body}"
    try:
        resp = safe_request(
            "POST",
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json_body={"chat_id": chat_id, "text": text[:4096]},
        )
    except Exception as e:
        return False, "telegram_transport_error"
    if resp.status_code != 200:
        return False, f"telegram_http_{resp.status_code}"
    return True, None


def _send_webhook(cfg: dict[str, Any], subject: str, body: str) -> tuple[bool, str | None]:
    url = str(cfg.get("url") or "").strip()
    if not url:
        return False, "invalid_destination"
    try:
        validate_webhook_destination(url)
    except Exception as e:
        return False, f"destination_rejected: {e}"
    try:
        resp = safe_request(
            "POST",
            url,
            headers={"Content-Type": "application/json"},
            json_body={"subject": subject, "body": body},
        )
    except Exception as e:
        return False, "webhook_transport_error"
    if 200 <= resp.status_code < 300:
        return True, None
    return False, f"webhook_http_{resp.status_code}"
