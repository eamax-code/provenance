from app.services import stats as stats_service


def test_stats_is_public_and_shaped(client, ingested_aapl):
    stats_service.reset_cache()
    r = client.get("/v1/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["companies"]["ingested"] == 1 and body["companies"]["known"] == 1
    assert body["filings"]["total"] == 6
    assert body["facts"]["total"] > 0 and set(body["facts"]["by_quality"]) >= {"ok"}
    assert body["freshness"]["last_successful_fetch_at"]
    assert "latest_filing_detected_at" not in body["freshness"]
    # The fixture filings are from 2023-2024, so none fall in the last 12 months.
    assert body["filings"]["last_12_months"] == 0 and body["companies"]["filed_last_12_months"] == 0
    assert body["ingestion"]["last_run_status"] == "succeeded"
    assert (
        body["notifications"]["pending_deliveries"] == 0
        and body["notifications"]["active_watches"] == 0
    )
    assert body["mapping_version"] == "1.4.1" and body["generated_at"].endswith("Z")
    assert body["cache_ttl_seconds"] >= 1
    assert body["source"] == "SEC EDGAR" and "not affiliated" in body["disclaimer"]
    assert "X-API-Key" not in r.request.headers
    text = r.text.lower()
    for forbidden in ("pepper", "secret", "postgres", "sqlite", "traceback"):
        assert forbidden not in text


def test_stats_empty_state(client):
    stats_service.reset_cache()
    body = client.get("/v1/stats").json()
    assert body["companies"]["ingested"] == 0 and body["filings"]["total"] == 0
    assert body["freshness"]["last_successful_fetch_at"] is None
    assert body["ingestion"]["last_run_status"] is None


def test_stats_is_served_from_the_snapshot_until_it_is_refreshed(client, db, sec_client, settings):
    from app.services.ingestion import ingest_company

    stats_service.reset_cache()
    first = client.get("/v1/stats").json()["companies"]["ingested"]
    ingest_company(db, sec_client, "320193")
    stats_service.reset_cache()
    assert client.get("/v1/stats").json()["companies"]["ingested"] == first  # stored snapshot
    stats_service.refresh_snapshot(db, settings)  # the background refresher
    assert client.get("/v1/stats").json()["companies"]["ingested"] == first + 1


def test_stats_rate_limited_per_ip(client, monkeypatch):
    from app.api import routes_stats

    stats_service.reset_cache()
    routes_stats.ip_limiter.reset()
    monkeypatch.setattr(routes_stats, "STATS_RATE_LIMIT_PER_MINUTE", 2)
    assert client.get("/v1/stats").status_code == 200
    assert client.get("/v1/stats").status_code == 200
    r = client.get("/v1/stats")
    assert (
        r.status_code == 429
        and "Retry-After" in r.headers
        and r.json()["error"]["code"] == "rate_limited"
    )
    routes_stats.ip_limiter.reset()


def test_stats_not_metered_and_openapi_has_no_security(client, auth, ingested_aapl):
    stats_service.reset_cache()
    client.get("/v1/stats")
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert "/v1/stats" not in usage["requests_by_route"]
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/stats"]["get"]["security"] == []


def test_landing_page_wires_live_stats(client):
    html = client.get("/").text
    assert "/v1/stats" in html and 'data-stat="companies"' in html
    assert "No companies ingested yet" in html or "not ingested anything yet" in html.lower()


def test_stats_health_branches_and_cache_header(client, db, ingested_aapl, settings):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.db.models import Company, IngestionRun

    stats_service.reset_cache()
    r = client.get("/v1/stats")
    assert (
        r.headers["Cache-Control"].startswith("public, max-age=")
        and r.json()["service"]["health"] == "ok"
    )
    c = db.scalar(select(Company).where(Company.cik == "0000320193"))
    c.last_successful_fetch_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()
    stats_service.refresh_snapshot(db, settings)
    assert client.get("/v1/stats").json()["service"]["health"] == "stale"
    c.last_successful_fetch_at = datetime.now(UTC)
    db.add(
        IngestionRun(
            source="sec:poll",
            status="failed",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            error_count=1,
        )
    )
    db.commit()
    stats_service.refresh_snapshot(db, settings)
    assert client.get("/v1/stats").json()["service"]["health"] == "degraded"
    stats_service.reset_cache()


def test_stats_are_served_from_the_stored_snapshot_without_aggregates(client, db, settings):
    """P-01: a request reads the stored snapshot; it never runs the aggregate queries."""
    from sqlalchemy import event

    from app.db.session import get_engine
    from app.services import stats

    stats.refresh_snapshot(db, settings)
    stats.reset_cache()
    seen: list[str] = []

    def record(conn, cursor, statement, *args):
        seen.append(statement.lower())

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        r = client.get("/v1/stats")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert r.status_code == 200 and r.json()["generated_at"]
    aggregates = [s for s in seen if "count(" in s or "max(" in s or "min(" in s]
    assert aggregates == [], aggregates[:2]
    # a stale snapshot is still served, with the time it was made
    old = r.json()["generated_at"]
    stats.reset_cache()
    assert client.get("/v1/stats").json()["generated_at"] == old
