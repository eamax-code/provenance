"""Operator alerts and the poller's daily retention purge (ticket 12)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.db.models import DataQualitySnapshot, IngestionRun
from app.jobs.poll_sec import maybe_purge
from app.services import alerts


@pytest.fixture(autouse=True)
def _fresh():
    alerts.reset()
    yield
    alerts.reset()


def _runs(db, *statuses):
    start = datetime(2026, 11, 6, tzinfo=UTC)
    for i, status in enumerate(statuses):
        db.add(
            IngestionRun(source="sec:poll", status=status, started_at=start + timedelta(minutes=i))
        )
    db.commit()


def _snap(**kw):
    return DataQualitySnapshot(
        oldest_pending_age_seconds=kw.get("age"),
        pending_deliveries=kw.get("pending", 0),
        detect_to_process_p95_s=kw.get("p95"),
        duplicate_filings=kw.get("dups", 0),
    )


def _webhook():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    return sent, httpx.Client(transport=httpx.MockTransport(handler))


def test_conditions(db, settings):
    _runs(db, "succeeded", "failed", "failed")
    found = alerts.conditions(db, settings, _snap(age=7200, pending=4, p95=3600, dups=1))
    assert set(found) == {
        "ingestion_failing",
        "delivery_backlog",
        "slow_processing",
        "duplicate_filings",
    }
    assert "120 minutes" in found["delivery_backlog"]
    db.query(IngestionRun).delete()
    _runs(db, "failed", "succeeded")
    assert alerts.conditions(db, settings, _snap(age=60, p95=60)) == {}


def test_posts_once_then_repeats_hourly_and_again_after_recovery(db, settings, monkeypatch):
    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.test/x")
    sent, http = _webhook()
    snap = _snap(age=7200, pending=2)
    assert alerts.check_and_notify(db, settings, snap, http=http, now=0) == ["delivery_backlog"]
    assert "deliveries are waiting" in sent[0]["text"] and sent[0]["content"] == sent[0]["text"]
    assert alerts.check_and_notify(db, settings, snap, http=http, now=600) == []
    assert alerts.check_and_notify(db, settings, snap, http=http, now=3600) == ["delivery_backlog"]
    assert alerts.check_and_notify(db, settings, _snap(age=10), http=http, now=3700) == []
    assert alerts.check_and_notify(db, settings, snap, http=http, now=3800) == ["delivery_backlog"]
    assert len(sent) == 3


def test_no_url_sends_nothing(db, settings):
    sent, http = _webhook()
    assert alerts.check_and_notify(db, settings, _snap(dups=3), http=http, now=0) == []
    assert sent == []


def test_retention_runs_once_a_day(db, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.retention.purge", lambda db, settings: calls.append(1) or {"api_usage": 0}
    )
    day1 = datetime(2026, 11, 6, 3, tzinfo=UTC)
    last = maybe_purge(db, settings, None, now=day1)
    last = maybe_purge(db, settings, last, now=day1 + timedelta(hours=5))
    last = maybe_purge(db, settings, last, now=day1 + timedelta(days=1))
    assert len(calls) == 2
    monkeypatch.setattr(settings, "retention_enabled", False)
    assert maybe_purge(db, settings, None, now=day1) is None and len(calls) == 2
