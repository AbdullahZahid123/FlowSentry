"""SSRF-safe outbound HTTP client.

ARCHITECTURE.md section 11.3:
- HTTPS by default; explicit allowlist for private-network deployments.
- Reject loopback/private/link-local/multicast/reserved/metadata IPs.
- Resolve hostnames and validate every resolved address.
- Validate redirect targets; redirects are followed only when every hop
  validates.
- Connection/read timeouts and bounded response sizes.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core import config
from app.core.errors import ApiError


class SsrfViolation(Exception):
    """Raised when a destination fails the egress policy."""


@dataclass(frozen=True)
class EgressPolicy:
    allow_private_network: bool = False

    @classmethod
    def default(cls) -> "EgressPolicy":
        return cls(allow_private_network=config.settings.allow_private_network)


def _validate_ip(addr: str, policy: EgressPolicy) -> None:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError as e:
        raise SsrfViolation("Invalid target address.") from e
    if policy.allow_private_network:
        return
    bad = (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
    if bad:
        raise SsrfViolation("The destination address is not permitted by the outbound policy.")


def resolve_url_and_validate(url: str, policy: EgressPolicy) -> list[str]:
    """Validate scheme + host resolution for a URL. Returns resolved IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise SsrfViolation("Only HTTP(S) URLs are allowed.")
    if parsed.scheme == "http" and not policy.allow_private_network:
        # Cleartext HTTP is only acceptable inside explicitly trusted private
        # networks; this must be deliberate administrator configuration.
        raise SsrfViolation("HTTPS is required by the outbound policy.")
    host = parsed.hostname
    if not host:
        raise SsrfViolation("A hostname is required.")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise SsrfViolation("Credentials and fragments are not permitted in destination URLs.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise SsrfViolation("Invalid destination port.") from exc
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise SsrfViolation("Cannot resolve the target hostname.") from e
    ips: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        ips.append(addr)
        _validate_ip(addr, policy)
    if not ips:
        raise SsrfViolation("Cannot resolve the target hostname.")
    return sorted(set(ips))


def validate_outbound_url(url: str) -> str:
    """Validate + normalize a user-supplied base URL. Raises ApiError on violation."""
    normalized = url.strip().rstrip("/")
    try:
        resolve_url_and_validate(normalized, EgressPolicy.default())
    except SsrfViolation as e:
        raise ApiError("validation_error", str(e), 422) from e
    return normalized


def validate_webhook_destination(url: str) -> str:
    """Webhook notification destinations must pass the egress controls."""
    try:
        resolve_url_and_validate(url.strip(), EgressPolicy.default())
    except SsrfViolation as e:
        raise ApiError("validation_error", f"Webhook URL rejected: {e}", 422) from e
    return url.strip()


def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
) -> httpx.Response:
    """Pin the validated destination IP, preserve TLS hostname verification,
    reject redirects, and bound decoded response bytes while streaming.
    """
    policy = EgressPolicy.default()
    timeout = timeout or config.settings.http_outbound_timeout_seconds
    size_cap = max_bytes or config.settings.http_outbound_max_bytes

    ips = resolve_url_and_validate(url, policy)
    original = httpx.URL(url)
    pinned = original.copy_with(host=ips[0])
    outgoing = dict(headers or {})
    outgoing["Host"] = original.netloc.decode("ascii")
    with httpx.Client(follow_redirects=False, timeout=timeout, trust_env=False) as client:
        with client.stream(method, pinned, headers=outgoing, json=json_body,
                extensions={"sni_hostname": original.host}) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                raise SsrfViolation("Redirects are not permitted. Configure the source's canonical HTTPS URL.")
            _enforce_size(resp, size_cap)
            content = bytearray()
            for chunk in resp.iter_bytes(chunk_size=16384):
                if len(content) + len(chunk) > size_cap:
                    raise SsrfViolation("Response exceeds the maximum allowed size.")
                content.extend(chunk)
            response_headers = dict(resp.headers)
            response_headers.pop("content-encoding", None)
            response_headers["content-length"] = str(len(content))
            return httpx.Response(resp.status_code, headers=response_headers, content=bytes(content),
                request=httpx.Request(method, url))


def _enforce_size(resp: httpx.Response, max_bytes: int) -> None:
    cl = resp.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        raise SsrfViolation("Response exceeds the maximum allowed size.")


def response_text(resp: httpx.Response, max_bytes: int | None = None) -> str:
    cap = max_bytes or config.settings.http_outbound_max_bytes
    return resp.content[:cap].decode("utf-8", errors="replace")
