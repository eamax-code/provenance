"""Q-03e: a per-process cache of whole responses that are slow to build, kept until the data they
read changes (and at most TTL seconds as a backstop).

The version is the data version the showcase cache already keeps (`showcase_cache.data_version`):
on PostgreSQL the writes counted in pg_stat_user_tables over the page's table group, re-read at
most every 30 seconds, so a Form 4 load or an F-03 correction retires every cached screen; on
other databases nothing is cached (tests give a version of their own). The key is every
parameter that shapes the response, including the demo key's scope. A hit is a deep copy, so a
caller can never change a cached answer.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable

_ALL: list[VersionedCache] = []


def reset_all() -> None:
    """Empty every response cache (tests: each has its own database)."""
    for c in _ALL:
        c.clear()


class VersionedCache:
    def __init__(self, path: str, ttl: float = 600, max_entries: int = 256,
                 version: Callable[[], Hashable] | None = None) -> None:  # fmt: skip
        self.path, self.ttl, self.max_entries = path, ttl, max_entries
        self._version = version
        self._lock = threading.Lock()
        self._entries: OrderedDict[Hashable, tuple[Hashable, float, dict]] = OrderedDict()
        self.hits = self.misses = 0
        _ALL.append(self)

    def version(self) -> Hashable | None:
        """The data version; None (never cache) without PostgreSQL's write counters, unless a
        version was given (tests)."""
        if self._version is not None:
            return self._version()
        from app.db.session import get_engine
        from app.services import showcase_cache

        if get_engine().dialect.name != "postgresql":
            return None
        return showcase_cache.data_version(path=self.path)

    def get_or_build(self, key: Hashable, build: Callable[[], dict]) -> dict:
        version, now = self.version(), time.monotonic()
        if version is None:
            return build()
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None and hit[0] == version and now - hit[1] < self.ttl:
                self._entries.move_to_end(key)
                self.hits += 1
                return copy.deepcopy(hit[2])
        value = build()
        with self._lock:
            self.misses += 1
            self._entries[key] = (version, now, copy.deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = self.misses = 0
