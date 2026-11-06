"""Rate limits shared through the database, so replicas count together (ticket 12)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import rate_limits
from app.core.rate_limits import FixedWindowRateLimiter
from app.db.models import RateLimitCounter


@pytest.fixture
def store():
    def use(name):
        rate_limits.configure(name)

    yield use
    rate_limits.configure("auto")


def test_two_replicas_share_one_limit(engine, db, store):
    store("database")
    a = FixedWindowRateLimiter(60, name="key-minute")  # one per replica, same name
    b = FixedWindowRateLimiter(60, name="key-minute")
    now = 1_800_000_000.0
    decisions = [(a if i % 2 else b).check("k1", 5, now=now) for i in range(7)]
    assert [d.allowed for d in decisions] == [True] * 5 + [False] * 2
    assert decisions[4].remaining == 0 and decisions[5].retry_after_seconds >= 1
    # Another key and the next window start from zero.
    assert a.check("k2", 5, now=now).remaining == 4
    assert b.check("k1", 5, now=now + 60).allowed
    row = db.scalar(select(RateLimitCounter).where(RateLimitCounter.key == "key-minute:k1"))
    assert row.count == 7


def test_memory_store_counts_per_process(engine, store):
    store("memory")
    a, b = FixedWindowRateLimiter(60, name="x"), FixedWindowRateLimiter(60, name="x")
    now = 1_800_000_000.0
    assert all(a.check("k", 2, now=now).allowed for _ in range(2))
    assert not a.check("k", 2, now=now).allowed
    assert b.check("k", 2, now=now).allowed  # its own counter: the per-replica behaviour


def test_database_outage_falls_back_to_memory(engine, store, monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError

    store("database")
    limiter = FixedWindowRateLimiter(60, name="key-minute")

    def down(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(limiter, "_count_in_db", down)
    monkeypatch.setattr(rate_limits, "_warned_at", 0.0)
    now = 1_800_000_000.0
    assert [limiter.check("k", 2, now=now).allowed for _ in range(3)] == [True, True, False]
    assert "rate-limit store unavailable" in caplog.text


def test_auto_uses_the_database_only_on_postgresql(engine, store):
    store("auto")
    assert (rate_limits._engine() is not None) == (engine.dialect.name == "postgresql")
    with pytest.raises(ValueError):
        rate_limits.configure("redis")


def test_retention_removes_finished_windows(engine, db, settings, store):
    from app.services import retention

    store("database")
    now = datetime(2026, 11, 6, tzinfo=UTC)
    limiter = FixedWindowRateLimiter(86400, name="demo-day")
    limiter.check("ip", 10, now=now.timestamp() - 5 * 86400)
    limiter.check("ip", 10, now=now.timestamp())
    assert retention.purge(db, settings, now=now)["rate_limit_counters"] == 1
    assert db.scalar(select(RateLimitCounter.count)) == 1
