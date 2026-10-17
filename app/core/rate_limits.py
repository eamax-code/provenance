"""In-process fixed-window rate limiter keyed by API key.

Single-process MVP. For multiple API replicas, move the counters to the database or a
shared store; see docs/operations.md.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class FixedWindowRateLimiter:
    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, int]] = {}  # key -> (window_start, count)

    def check(self, key: str, limit: int, now: float | None = None) -> RateDecision:
        current = now if now is not None else time.time()
        window_start = int(current // self.window_seconds) * self.window_seconds
        with self._lock:
            start, count = self._counters.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            if count >= limit:
                retry_after = max(1, int(start + self.window_seconds - current) + 1)
                self._counters[key] = (start, count)
                return RateDecision(False, limit, 0, retry_after)
            count += 1
            self._counters[key] = (start, count)
            if len(self._counters) > 50_000:
                stale = [k for k, (s, _) in self._counters.items() if s != window_start]
                for k in stale:
                    self._counters.pop(k, None)
            return RateDecision(True, limit, limit - count, 0)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
