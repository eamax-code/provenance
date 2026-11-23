"""Single-flight for per-process caches: on a miss, the first caller for a key computes, and
concurrent callers for the same key wait for it, then read the cache, instead of all
computing the same thing at once (R-2, 2026-11-23: the cold keyless burst).

A waiter stops waiting after WAIT_SECONDS, and when the leader produced nothing cacheable (an
error, a 404) the waiter computes itself, so a slow or failed leader never blocks anyone for
long. Per process only: each worker fills its own cache.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Hashable

WAIT_SECONDS = 15.0


class SingleFlight:
    """For synchronous code (request handlers run in the threadpool)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[Hashable, threading.Event] = {}

    def acquire(self, key: Hashable) -> tuple[bool, threading.Event]:
        """(True, event) when this caller leads and must call release; (False, event) to wait."""
        with self._lock:
            event = self._inflight.get(key)
            if event is None:
                event = self._inflight[key] = threading.Event()
                return True, event
            return False, event

    def release(self, key: Hashable) -> None:
        with self._lock:
            event = self._inflight.pop(key, None)
        if event is not None:
            event.set()

    def wait(self, event: threading.Event) -> None:
        event.wait(WAIT_SECONDS)


class AsyncSingleFlight:
    """For code on the event loop (middleware)."""

    def __init__(self) -> None:
        self._inflight: dict[Hashable, asyncio.Event] = {}

    def acquire(self, key: Hashable) -> tuple[bool, asyncio.Event]:
        event = self._inflight.get(key)
        if event is None:
            event = self._inflight[key] = asyncio.Event()
            return True, event
        return False, event

    def release(self, key: Hashable) -> None:
        event = self._inflight.pop(key, None)
        if event is not None:
            event.set()

    async def wait(self, event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(event.wait(), WAIT_SECONDS)
        except TimeoutError:
            pass
