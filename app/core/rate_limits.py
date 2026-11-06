"""Fixed-window rate limits, shared by every API replica.

On PostgreSQL (or with RATE_LIMIT_STORE=database) each check is one atomic upsert on
`rate_limit_counters` (key, window start) -> count, so two replicas count together. With
RATE_LIMIT_STORE=memory, or on SQLite under the default "auto", counters stay in process memory.

If the database cannot be reached, a check falls back to this process's memory counter and logs a
warning at most once a minute: limits then hold per replica rather than failing every request.
See docs/operations.md.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("app.rate_limits")

STORES = ("auto", "memory", "database")
_store = "auto"
_warned_at = 0.0
_checks = 0
CLEANUP_EVERY = 1000  # checks per process between deletions of finished windows
KEEP_SECONDS = 2 * 86400  # longer than the longest window (a day)


def configure(store: str) -> None:
    """Where counters live: "auto" (the database on PostgreSQL), "memory" or "database"."""
    global _store
    if store not in STORES:
        raise ValueError(f"rate_limit_store must be one of {STORES}")
    _store = store


@dataclass
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def _engine():
    if _store == "memory":
        return None
    from app.db.session import get_engine

    engine = get_engine()
    if _store == "auto" and engine.dialect.name != "postgresql":
        return None
    return engine


class FixedWindowRateLimiter:
    def __init__(self, window_seconds: int = 60, name: str | None = None) -> None:
        self.window_seconds = window_seconds
        self.name = name or f"w{window_seconds}"
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, int]] = {}  # key -> (window_start, count)

    def check(self, key: str, limit: int, now: float | None = None) -> RateDecision:
        current = now if now is not None else time.time()
        window_start = int(current // self.window_seconds) * self.window_seconds
        retry_after = max(1, int(window_start + self.window_seconds - current) + 1)
        engine = _engine()
        if engine is not None:
            try:
                count = self._count_in_db(engine, key, window_start, current)
                if count > limit:
                    return RateDecision(False, limit, 0, retry_after)
                return RateDecision(True, limit, limit - count, 0)
            except SQLAlchemyError as exc:
                _warn_outage(exc)
        return self._check_memory(key, limit, window_start, retry_after)

    def _count_in_db(self, engine, key: str, window_start: int, current: float) -> int:
        from sqlalchemy import delete

        from app.db.models import RateLimitCounter

        if engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        stmt = insert(RateLimitCounter).values(
            key=f"{self.name}:{key}", window_start=window_start, count=1
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key", "window_start"],
            set_={"count": RateLimitCounter.count + 1},
        ).returning(RateLimitCounter.count)
        global _checks
        _checks += 1
        with engine.begin() as conn:
            count = conn.execute(stmt).scalar_one()
            if _checks % CLEANUP_EVERY == 0:
                conn.execute(
                    delete(RateLimitCounter).where(
                        RateLimitCounter.window_start < int(current) - KEEP_SECONDS
                    )
                )
        return int(count)

    def _check_memory(self, key: str, limit: int, window_start: int, retry_after: int):
        with self._lock:
            start, count = self._counters.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            if count >= limit:
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
        """Clear this limiter's counters, in memory and in the shared table (tests, operators)."""
        with self._lock:
            self._counters.clear()
        engine = _engine()
        if engine is None:
            return
        from sqlalchemy import delete

        from app.db.models import RateLimitCounter

        try:
            with engine.begin() as conn:
                conn.execute(
                    delete(RateLimitCounter).where(RateLimitCounter.key.startswith(self.name + ":"))
                )
        except SQLAlchemyError as exc:
            _warn_outage(exc)


def _warn_outage(exc: Exception) -> None:
    global _warned_at
    now = time.monotonic()
    if now - _warned_at >= 60:
        _warned_at = now
        logger.warning(
            "rate-limit store unavailable; limits are per replica until it returns",
            extra={"extra_fields": {"error": type(exc).__name__}},
        )
