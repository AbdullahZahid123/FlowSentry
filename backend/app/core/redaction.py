"""Payload redaction.

Default posture is metadata-only storage (ARCHITECTURE.md section 11.5):
redact likely secrets, tokens, authorization headers, and personal data
before persisting any provider-provided payload.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

SENSITIVE_KEY_PATTERNS = [
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "api-key",
    "apikey",
    "credential",
    "credentials",
    "cookie",
    "session",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "client_secret",
    "bearer",
    "signature",
    "webhook",
    "bot_token",
    "card",
    "cvv",
    "ssn",
    "iban",
    "creditcart",
    "email",
    "emailaddress",
    "mail",
]

REDACTED = "[REDACTED]"

_JWT_RE = re.compile(r"\b[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{5,}\b")
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9\-._~+/=]{8,}\b")
_URL_KEY_RE = re.compile(r"(?i)([?&](?:api_?key|token|access_token|key|secret|password)=)[^&\s]+")
_INLINE_SECRET_RE = re.compile(r'''(?i)(\b(?:api[_-]?key|password|passwd|client_secret|access_token)\s*[:=]\s*)["']?[^\s,;"']+''')
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")


def _is_sensitive_key(key: str) -> bool:
    k = key.lower().strip()
    return any(p in k for p in SENSITIVE_KEY_PATTERNS)


def redact_value(obj: Any, depth: int = 0) -> Any:
    """Recursively redact a JSON-able structure."""
    if depth > 8:
        return REDACTED
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            if _is_sensitive_key(ks):
                out[ks] = REDACTED
            else:
                out[ks] = redact_value(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [redact_value(v, depth + 1) for v in obj[:50]]
    if isinstance(obj, str):
        s = redact_string(obj)
        return s
    return obj


def redact_string(s: str) -> str:
    if not s:
        return s
    s = _JWT_RE.sub(REDACTED, s)
    s = _BEARER_RE.sub(r"\1 " + REDACTED, s)
    s = _URL_KEY_RE.sub(r"\1" + REDACTED, s)
    s = _INLINE_SECRET_RE.sub(r"\1" + REDACTED, s)
    s = _EMAIL_RE.sub(REDACTED, s)
    return s


def normalize_text_for_fingerprint(s: str) -> str:
    """Normalize dynamic values so identical underlying errors group together."""
    if not s:
        return ""
    s = re.sub(r"\r\n", "\n", s)
    # URLs: keep path structure, drop query/fragment and dynamic ids
    s = re.sub(r"https?://[^\s'\"]+", lambda m: m.group(0).split("?")[0].split("#")[0], s)
    s = _UUID_RE.sub("<uuid>", s)
    s = re.sub(r"\b\d{1,5}(?:\.\d{1,5}){3}\b", "<ip>", s)
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(:\d{2})?(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b", "<ts>", s)
    s = re.sub(r"\b\d{10,14}\b", "<epoch>", s)
    s = _LONG_TOKEN_RE.sub("<token>", s)
    s = re.sub(r"\b\d+\b", "<n>", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def error_message_template(message: str | None, max_len: int = 300) -> str:
    if message is None:
        return ""
    t = normalize_text_for_fingerprint(message)
    return t[:max_len]


def payload_hash(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
