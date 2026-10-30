import pytest

DEMO = {"X-API-Key": "demo"}


@pytest.fixture(autouse=True)
def _reset_limits():
    from app.api import dependencies
    from app.services import public as public_service

    dependencies.demo_minute_limiter.reset()
    dependencies.demo_day_limiter.reset()
    public_service.reset_cache()
    yield
    dependencies.demo_minute_limiter.reset()
    dependencies.demo_day_limiter.reset()


def _seed_listing(db):
    from datetime import UTC, datetime, timedelta

    from app.services.markets import ingest
    from app.services.markets.records import ListingRecord

    ingest.ensure_market(db, "XPAR", "Euronext Paris", "FR", "europe", "esma_firds", "https://x")
    db.commit()
    now = datetime.now(UTC)
    ingest.ingest_records(
        db,
        [
            ListingRecord(
                isin="FR001400AJ45",
                mic="XPAR",
                issuer_name="Exosens",
                source="esma_firds",
                source_url="https://x",
                first_trade_date=now.date() - timedelta(days=2),
            )
        ],
        "esma_firds",
        now=now,
    )


def test_demo_key_reads_showcase_company_endpoints(client, ingested_aapl):
    for path in (
        "/v1/companies/320193",
        "/v1/companies/320193/filings?limit=5",
        "/v1/companies/320193/facts?metric=revenue",
        "/v1/companies/320193/freshness",
        "/v1/companies/search?q=apple",
        "/v1/companies?limit=5",
        "/v1/facts/screen?metric=revenue&year=2024&limit=5",
    ):
        r = client.get(path, headers=DEMO)
        assert r.status_code == 200, (path, r.text)
    # query-parameter form so a demo URL can be pasted into a browser
    assert client.get("/v1/companies/320193/filings?api_key=demo&limit=3").status_code == 200


def test_demo_key_reads_listings(client, db):
    _seed_listing(db)
    for path in (
        "/v1/markets/",
        "/v1/markets/events?limit=5",
        "/v1/markets/instruments?region=europe&limit=5",
        "/v1/markets/instruments/FR001400AJ45",
    ):
        assert client.get(path, headers=DEMO).status_code == 200, path


def test_demo_key_cannot_touch_accounts_or_exports(client, ingested_aapl):
    for method, path in (
        ("get", "/v1/developer/usage"),
        ("get", "/v1/developer/api-keys"),
        ("get", "/v1/watches"),
        ("get", "/v1/exports/facts?metric=revenue"),
        ("post", "/v1/watches"),
    ):
        r = getattr(client, method)(
            path, headers=DEMO, **({"json": {}} if method == "post" else {})
        )
        assert r.status_code == 401, (path, r.status_code)
    # the query-parameter form never authenticates real keys
    assert client.get("/v1/developer/usage?api_key=demo").status_code == 401


def test_demo_limits_page_size_and_showcase_scope(client, ingested_aapl, settings):
    r = client.get("/v1/companies/320193/filings?limit=50", headers=DEMO)
    assert (
        r.status_code == 403
        and r.json()["error"]["code"] == "demo_limit"
        and "limit" in r.json()["error"]["message"]
    )
    r = client.get("/v1/companies/789019/filings", headers=DEMO)  # not ingested, not in showcase
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_scope"


def test_demo_never_triggers_sec_ingestion(client, fake_sec):
    before = len(fake_sec.calls)
    r = client.get("/v1/companies/999", headers=DEMO)
    assert r.status_code == 403 and len(fake_sec.calls) == before


def test_demo_rate_limit_and_not_metered(client, ingested_aapl, auth, monkeypatch, settings):
    monkeypatch.setattr(settings, "demo_rate_limit_per_minute", 2)
    assert client.get("/v1/companies/search?q=apple", headers=DEMO).status_code == 200
    assert client.get("/v1/companies/search?q=apple", headers=DEMO).status_code == 200
    r = client.get("/v1/companies/search?q=apple", headers=DEMO)
    assert (
        r.status_code == 429
        and "Retry-After" in r.headers
        and "free key" in r.json()["error"]["message"]
    )
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert "/v1/companies/search" not in usage["requests_by_route"]


def test_demo_can_be_disabled(client, ingested_aapl, settings, monkeypatch):
    monkeypatch.setattr(settings, "demo_key_enabled", False)
    r = client.get("/v1/companies/search?q=apple", headers=DEMO)
    assert r.status_code == 401


def test_playground_page_is_served(client):
    r = client.get("/playground/")
    assert r.status_code == 200 and 'id="playground"' in r.text and "/playground.js" in r.text
    js = client.get("/playground.js").text
    for route in (
        "/v1/companies/search",
        "/v1/companies/{cik}/facts",
        "/v1/markets/events",
        "/v1/facts/screen",
    ):
        assert route in js
    assert "demo" in js and "curl" in js
    assert "/playground/" in client.get("/").text
