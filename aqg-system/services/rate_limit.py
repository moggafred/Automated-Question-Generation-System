"""In-process sliding-window rate limiter.

A deliberately dependency-free token bucket keyed by client address. It is
suitable for a single-process deployment (the default) and degrades to a
per-process limit behind multiple uvicorn workers, which is the documented
behaviour rather than a silent surprise.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque

from config.settings import settings


class SlidingWindowRateLimiter:
    """Counts requests per key within a rolling time window."""

    def __init__(self, max_requests: int | None = None, window_seconds: int | None = None):
        self.max_requests = int(
            max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
        )
        self.window_seconds = float(
            window_seconds if window_seconds is not None else settings.RATE_LIMIT_WINDOW_SECONDS
        )
        self._hits: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def allow(self, key: str) -> tuple[bool, int, int]:
        """Registers a hit and reports ``(allowed, remaining, retry_after_seconds)``."""
        now = time.monotonic()
        window_start = now - self.window_seconds

        with self._lock:
            self._sweep(window_start, now)
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= window_start:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = int(max(1.0, round(bucket[0] + self.window_seconds - now)))
                return False, 0, retry_after

            bucket.append(now)
            remaining = max(0, self.max_requests - len(bucket))
            return True, remaining, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _sweep(self, window_start: float, now: float) -> None:
        """Drops idle buckets, and fully sweeps at most once per window."""
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= window_start]
        for key in stale:
            self._hits.pop(key, None)


_limiter = SlidingWindowRateLimiter()


def get_limiter() -> SlidingWindowRateLimiter:
    """Returns the process-wide limiter instance."""
    return _limiter


__all__ = ["SlidingWindowRateLimiter", "get_limiter"]