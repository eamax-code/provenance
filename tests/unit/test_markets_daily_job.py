from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import IngestionRun
from app.jobs import markets as job


def test_is_due_respects_hour_enabled_and_once_per_day(db, settings, monkeypatch):
    early = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    late = datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
    assert job.is_due(db, settings, now=early) is False
    assert job.is_due(db, settings, now=late) is True
    monkeypatch.setattr(settings, "markets_daily_enabled", False)
    assert job.is_due(db, settings, now=late) is False
    monkeypatch.setattr(settings, "markets_daily_enabled", True)
    monkeypatch.setattr(settings, "markets_sources_enabled", "")
    assert job.is_due(db, settings, now=late) is False


def test_maybe_run_runs_once_per_day_and_records_run(db, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        job.firds,
        "ingest_firds",
        lambda db, s, http, source, **kw: (
            calls.append(source) or {"files_processed": 0, "errors": []}
        ),
    )
    monkeypatch.setattr(
        job.gleif,
        "enrich_issuers",
        lambda db, s, http, **kw: calls.append("gleif") or {"looked_up": 0},
    )
    monkeypatch.setattr(
        job, "MarketHttp", lambda settings: type("H", (), {"close": lambda self: None})()
    )
    late = datetime(2026, 10, 24, 11, 0, tzinfo=UTC)
    out = job.maybe_run(db, settings, now=late)
    assert out["status"] == "succeeded" and calls == ["esma_firds", "fca_firds", "gleif"]
    run = db.scalar(select(IngestionRun).where(IngestionRun.source == "markets:daily"))
    assert run.status == "succeeded"
    assert job.maybe_run(db, settings, now=late) is None  # already ran today
    assert job.is_due(db, settings, now=datetime(2026, 10, 25, 11, 0, tzinfo=UTC)) is True


def test_run_all_isolates_source_failures(db, settings, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("register down")

    monkeypatch.setattr(job.firds, "ingest_firds", boom)
    monkeypatch.setattr(job.gleif, "enrich_issuers", lambda db, s, http, **kw: {"looked_up": 0})
    monkeypatch.setattr(
        job, "MarketHttp", lambda settings: type("H", (), {"close": lambda self: None})()
    )
    out = job.run_all(db, settings)
    assert (
        out["status"] == "partial"
        and "esma_firds: RuntimeError" in out["errors"]
        and "gleif" in out["sources"]
    )


def test_seconds_until_next_run(settings):
    assert (
        job.seconds_until_next_run(settings, now=datetime(2026, 10, 24, 9, 0, tzinfo=UTC)) == 3600
    )
    assert (
        job.seconds_until_next_run(settings, now=datetime(2026, 10, 24, 10, 30, tzinfo=UTC))
        == 23 * 3600 + 1800
    )
