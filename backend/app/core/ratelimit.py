"""Simple in-process sliding-window rate limiter.

Per API_SPECIFICATION.md section 17 limits are kept per key (per integration
ingress token, per account for login). This is a single-process limiter —
documented and acceptable for the MVP deployment envelope; multi-replica
deployments should add a shared counter store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimitState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            cutoff = now - window_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                retry_after = int(max(1.0, window_seconds - (now - q[0])))
                return False, retry_after
            q.append(now)
            return True, 0


rate_limiter = RateLimitState()


def allow(key: str, limit: int, window_seconds: float = 60.0) -> tuple[bool, int]:
    return rate_limiter.check(key, limit, window_seconds)
