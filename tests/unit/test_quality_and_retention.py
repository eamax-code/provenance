from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import ApiUsage, DataQualitySnapshot, IngestionRun, NotificationDelivery
from app.services import quality, retention
from app.services.ingestion import ingest_company


def test_snapshot_after_ingestion_has_counts(db, settings, sec_client):
    result = ingest_company(db, sec_client, "320193")
    snap = quality.take_snapshot(db, settings, run_id=result.run_id)
    db.commit()
    assert snap.companies_ingested == 1 and snap.filings_total == 6
    assert (
        snap.facts_total > 0
        and snap.facts_ok > 0
        and snap.facts_ambiguous > 0
        and snap.facts_invalid == 1
    )
    assert snap.facts_with_provenance_pct == 100.0
    assert snap.duplicate_filings == 0 and snap.companies_stale == 0
    assert snap.pending_deliveries == 0 and snap.run_id == result.run_id
    latest = quality.latest_snapshot(db)
    assert latest.id == snap.id
    d = quality.snapshot_to_dict(snap)
    assert d["taken_at"].endswith("Z") and d["facts"]["by_quality"]["ok"] == snap.facts_ok


def test_snapshot_on_empty_database_does_not_invent_provenance(db, settings):
    snap = quality.take_snapshot(db, settings)
    assert snap.facts_total == 0 and snap.facts_with_provenance_pct is None


def test_snapshot_counts_stale_companies(db, settings, sec_client):
    ingest_company(db, sec_client, "320193")
    from app.db.models import Company

    c = db.scalar(select(Company).where(Company.cik == "0000320193"))
    c.last_successful_fetch_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()
    snap = quality.take_snapshot(db, settings)
    assert snap.companies_stale == 1


def test_sec_request_metrics_recorded_on_run(db, settings, sec_client, fake_sec):
    fake_sec.fail_statuses = [503]
    result = ingest_company(db, sec_client, "320193")
    run = db.get(IngestionRun, result.run_id)
    assert run.sec_requests == 3 and run.sec_retries == 1 and run.sec_duration_ms >= 0
    # second ingestion is served from the ETag cache (304s still count as requests)
    result2 = ingest_company(db, sec_client, "320193")
    run2 = db.get(IngestionRun, result2.run_id)
    assert run2.sec_requests == 2 and run2.sec_cached == 2 and run2.sec_retries == 0
    # Responses by endpoint and status: the 503 and its retry, then 304s from the cache.
    import json

    first = json.loads(run.sec_by_endpoint)
    assert (
        sum(first.values()) == 3
        and first.get("submissions 503", 0) + first.get("companyfacts 503", 0) == 1
    )
    assert json.loads(run2.sec_by_endpoint) == {"companyfacts 304": 1, "submissions 304": 1}


def test_endpoint_kinds_and_metric_deltas():
    from app.services.sec_client import SecMetrics, endpoint_kind

    assert endpoint_kind("https://data.sec.gov/submissions/CIK0000320193.json") == "submissions"
    assert endpoint_kind("https://data.sec.gov/api/xbrl/companyfacts/CIK1.json") == "companyfacts"
    assert endpoint_kind("https://www.sec.gov/Archives/edgar/data/1/x.htm") == "archives"
    assert endpoint_kind("https://www.sec.gov/files/company_tickers_exchange.json") == "tickers"
    assert endpoint_kind("https://example.com/") == "other"
    m = SecMetrics()
    m.count("https://www.sec.gov/Archives/a", 200)
    before = m.snapshot()
    m.count("https://www.sec.gov/Archives/b", 200)
    m.count("https://www.sec.gov/Archives/c", "network")
    assert m.delta(before)["by_endpoint"] == {"archives 200": 1, "archives network": 1}


def test_snapshot_has_detection_to_processing_percentiles(db, settings, sec_client):
    from app.db.models import Filing

    ingest_company(db, sec_client, "320193")
    now = datetime.now(UTC)
    filings = db.scalars(select(Filing).order_by(Filing.accession_number)).all()
    for i, f in enumerate(filings):  # waits of 10, 20, 30 ... seconds
        f.first_detected_at = now - timedelta(minutes=5)
        f.processed_at = f.first_detected_at + timedelta(seconds=10 * (i + 1))
    db.commit()
    snap = quality.take_snapshot(db, settings, now=now)
    n = len(filings)
    assert snap.processed_24h == n
    assert snap.detect_to_process_p50_s == 10 * ((n + 1) // 2)
    assert snap.detect_to_process_p95_s == 10 * max(1, -(-95 * n // 100))
    shown = quality.snapshot_to_dict(snap)["latency"]
    assert shown["detect_to_process_p95_seconds"] == snap.detect_to_process_p95_s
    assert "latency: processed_24h=" in quality.render_report(db)
    assert quality.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0


def test_poll_run_writes_snapshot(db, settings, sec_client, tickers_payload):
    from app.db.models import CompanyWatch
    from app.jobs.poll_sec import run_once
    from app.services.api_keys import create_key_record
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(db, tickers_payload)
    key, _ = create_key_record(db, settings, "p@example.com", "free", None, actor="test")
    db.add(
        CompanyWatch(
            api_key_id=key.id,
            cik="0000320193",
            destination_type="webhook",
            destination="https://hooks.example.com/",
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    summary = run_once(db, settings, client=sec_client)
    import uuid

    assert summary["snapshot_id"]
    snap = db.get(DataQualitySnapshot, uuid.UUID(summary["snapshot_id"]))
    assert snap.companies_ingested == 1 and snap.universe_active == 1


def test_stats_includes_latest_snapshot(client, db, settings, ingested_aapl):
    from app.services import stats as stats_service

    quality.take_snapshot(db, settings, run_id=ingested_aapl.run_id)
    db.commit()
    stats_service.reset_cache()
    body = client.get("/v1/stats").json()
    assert body["quality_snapshot"]["facts"]["total"] > 0
    assert body["quality_snapshot"]["taken_at"]


def test_retention_purges_only_beyond_window(db, settings, sec_client):
    from app.services.api_keys import create_key_record

    key, _ = create_key_record(db, settings, "r@example.com", "free", None, actor="test")
    now = datetime(2026, 10, 18, tzinfo=UTC)
    old = now - timedelta(days=settings.usage_retention_days + 1)
    fresh = now - timedelta(days=settings.usage_retention_days - 1)
    for when in (old, old, fresh):
        db.add(
            ApiUsage(
                api_key_id=key.id,
                request_id="req_x",
                route_template="/x",
                http_status=200,
                occurred_at=when,
            )
        )
    ingest_company(db, sec_client, "320193")
    from app.db.models import CompanyWatch, Filing

    w = CompanyWatch(
        api_key_id=key.id,
        cik="0000320193",
        destination_type="webhook",
        destination="https://h.example.com/",
        is_active=True,
        created_at=now,
    )
    db.add(w)
    db.flush()
    filing = db.scalar(select(Filing))
    old_d = now - timedelta(days=settings.delivery_retention_days + 1)
    for i, (status, when) in enumerate(
        [("delivered", old_d), ("failed", old_d), ("pending", old_d), ("delivered", now)]
    ):
        db.add(
            NotificationDelivery(
                watch_id=w.id,
                filing_id=filing.id,
                event_id=f"evt_{i}",
                status=status,
                created_at=when,
                next_attempt_at=now if status == "pending" else None,
            )
        )
    db.commit()
    counts = retention.purge(db, settings, now=now)
    assert counts == {"api_usage": 2, "notification_deliveries": 2}
    assert db.scalar(select(func.count(ApiUsage.id))) == 1
    remaining = {d.status for d in db.scalars(select(NotificationDelivery))}
    assert remaining == {"pending", "delivered"}  # pending is never purged
    assert retention.purge(db, settings, now=now) == {"api_usage": 0, "notification_deliveries": 0}


def test_quality_report_renders(db, settings, sec_client):
    ingest_company(db, sec_client, "320193")
    quality.take_snapshot(db, settings)
    db.commit()
    text = quality.render_report(db, limit=5)
    assert "facts" in text.lower() and "ambiguous" in text.lower() and "0000320193" not in text
