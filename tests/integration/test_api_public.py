from app.services import public as public_service


def _reset():
    from app.api import routes_public

    public_service.reset_cache()
    routes_public.ip_limiter.reset()


def test_plans_are_public_and_match_config(client):
    _reset()
    r = client.get("/v1/public/plans")
    assert r.status_code == 200, r.text
    body = r.json()
    names = [p["name"] for p in body["data"]]
    assert names == ["free", "builder", "team", "enterprise"]  # internal and legacy pilot hidden
    builder = next(p for p in body["data"] if p["name"] == "builder")
    assert builder["featured"] is True and builder["rate_limit_per_minute"] == 300
    assert builder["monthly_request_quota"] == 250_000 and builder["max_watches"] == 50
    assert body["max_export_rows"] == 1000 and "not affiliated" in body["disclaimer"]
    assert r.headers["Cache-Control"].startswith("public, max-age=")


def test_showcase_list_default_is_recent_ingested_companies(
    client, db, sec_client, tickers_payload, fake_sec
):
    from app.services.ingestion import import_ticker_mapping, ingest_company

    _reset()
    import_ticker_mapping(db, tickers_payload)  # known but not ingested companies must not appear
    ingest_company(db, sec_client, "320193")
    ingest_company(db, sec_client, "789019")
    db.commit()
    calls_before = len(fake_sec.calls)
    r = client.get("/v1/public/companies")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [c["cik"] for c in data] == [
        "0000320193",
        "0000789019",
    ]  # AAPL filed 2024-11, MSFT 2024-07
    aapl = data[0]
    assert aapl["legal_name"] == "Apple Inc." and aapl["ticker"] == "AAPL"
    assert (
        aapl["latest_filing"]["form_type"] == "10-K"
        and aapl["latest_filing"]["filing_date"] == "2024-11-01"
    )
    rev = aapl["latest_annual_revenue"]
    assert (
        rev["value"] == 391035000000 and rev["unit"] == "USD" and rev["period_end"] == "2024-09-28"
    )
    assert rev["source_url"].startswith("https://www.sec.gov/") and rev["accession_number"]
    assert data[1]["latest_annual_revenue"] is None  # MSFT revenue is ambiguous in the fixture
    assert len(fake_sec.calls) == calls_before  # no SEC call from public endpoints
    assert r.json()["meta"]["showcase_source"] == "recent"


def test_showcase_configured_list_and_cap(client, db, sec_client, settings, monkeypatch):
    from app.services.ingestion import ingest_company

    _reset()
    ingest_company(db, sec_client, "320193")
    ingest_company(db, sec_client, "789019")
    db.commit()
    monkeypatch.setattr(settings, "public_showcase_ciks", "789019")
    body = client.get("/v1/public/companies").json()
    assert [c["cik"] for c in body["data"]] == ["0000789019"] and body["meta"][
        "showcase_source"
    ] == "configured"
    assert client.get("/v1/public/companies/320193").status_code == 404  # outside the showcase
    _reset()
    monkeypatch.setattr(settings, "public_showcase_ciks", "")
    monkeypatch.setattr(settings, "public_showcase_limit", 1)
    assert [c["cik"] for c in client.get("/v1/public/companies").json()["data"]] == ["0000320193"]


def test_company_bundle(client, ingested_aapl, fake_sec):
    _reset()
    calls_before = len(fake_sec.calls)
    r = client.get("/v1/public/companies/320193")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["company"]["cik"] == "0000320193" and b["company"]["source_url"].startswith(
        "https://data.sec.gov/"
    )
    assert len(b["filings"]) == 6 and b["filings"][0]["accession_number"] == "0000320193-24-000123"
    assert (
        b["filings"][0]["accepted_at"] == "2024-11-01T06:01:36Z"
        and b["filings"][0]["source_published_at"] is None
    )
    metrics = {m["metric"]: m for m in b["metrics"]}
    assert set(metrics) == {
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
        "operating_cash_flow",
    }
    rev = metrics["revenue"]["facts"]
    assert [f["period_end"] for f in rev] == ["2024-09-28", "2023-09-30"]
    assert (
        rev[0]["value"] == 391035000000
        and rev[0]["mapping_version"] == "1.0.0"
        and rev[0]["quality_status"] == "ok"
    )
    assert rev[0]["source_tag"] and rev[0]["source_url"].startswith("https://www.sec.gov/")
    assert metrics["total_assets"]["facts"][0]["period_type"] == "instant"
    assert (
        b["freshness"]["status"] == "ok"
        and b["freshness"]["latest_filing"]["publication_to_detection_seconds"] is None
    )
    assert any("not affiliated" in n for n in b["notes"]) and "mapping_version" in b
    assert len(fake_sec.calls) == calls_before
    text = r.text.lower()
    for forbidden in ("api_key", "key_hash", "pepper", "owner_email", "watch"):
        assert forbidden not in text


def test_company_bundle_reports_absent_metrics(client, db, sec_client):
    from app.services.ingestion import ingest_company

    _reset()
    ingest_company(
        db, sec_client, "789019"
    )  # MSFT fixture lacks net income and operating cash flow
    db.commit()
    b = client.get("/v1/public/companies/789019").json()
    metrics = {m["metric"]: m for m in b["metrics"]}
    assert metrics["net_income"]["facts"] == [] and metrics["net_income"]["status"] == "unavailable"
    assert metrics["revenue"]["status"] == "ambiguous_mapping" and metrics["revenue"]["facts"] == []
    assert metrics["total_assets"]["status"] == "ok"


def test_public_404s_do_not_trigger_ingestion(client, fake_sec, db, tickers_payload):
    from app.services.ingestion import import_ticker_mapping

    _reset()
    import_ticker_mapping(db, tickers_payload)
    db.commit()
    before = len(fake_sec.calls)
    r = client.get("/v1/public/companies/1318605")  # known from tickers, never ingested
    assert r.status_code == 404 and r.json()["error"]["code"] == "company_not_found"
    assert client.get("/v1/public/companies/abc").status_code == 422
    assert len(fake_sec.calls) == before


def test_public_cache_and_rate_limit(client, ingested_aapl, monkeypatch):
    from app.api import routes_public

    _reset()
    first = client.get("/v1/public/companies").json()["generated_at"]
    assert client.get("/v1/public/companies").json()["generated_at"] == first
    monkeypatch.setattr(routes_public, "PUBLIC_RATE_LIMIT_PER_MINUTE", 3)
    routes_public.ip_limiter.reset()
    for _ in range(3):
        assert client.get("/v1/public/plans").status_code == 200
    r = client.get("/v1/public/plans")
    assert r.status_code == 429 and "Retry-After" in r.headers
    routes_public.ip_limiter.reset()


def test_public_endpoints_not_metered_and_in_openapi(client, auth, ingested_aapl):
    _reset()
    client.get("/v1/public/plans")
    client.get("/v1/public/companies")
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert not any(route.startswith("/v1/public") for route in usage["requests_by_route"])
    spec = client.get("/openapi.json").json()
    for path in ("/v1/public/plans", "/v1/public/companies", "/v1/public/companies/{cik}"):
        assert spec["paths"][path]["get"]["security"] == []
    assert "/v1/public/companies" in client.get("/llms.txt").text


def test_public_pages_are_served(client):
    for path in ("/companies/", "/status/", "/companies/0000320193"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), path
        assert (
            "not affiliated" in r.text.lower()
            and "/site/public.js" in r.text
            or "/public.js" in r.text
        ), path
    assert "/v1/public/companies" in client.get("/public.js").text
    html = client.get("/").text
    assert (
        "/v1/public/plans" in html and "/v1/public/companies" in html and 'id="live-data"' in html
    )


def test_public_listing_events_and_page(client, db):
    from datetime import UTC, datetime, timedelta

    from app.services.markets import ingest
    from app.services.markets.records import ListingRecord

    _reset()
    ingest.ensure_market(
        db,
        "XPAR",
        "Euronext Paris",
        "FR",
        "europe",
        "esma_firds",
        "https://registers.esma.europa.eu/",
    )
    db.commit()
    now = datetime.now(UTC)
    ingest.ingest_records(
        db,
        [
            ListingRecord(
                isin="FR001400AJ45",
                mic="XPAR",
                issuer_name="Exosens",
                issuer_lei="969500ABCDEFGHIJ1234",
                source="esma_firds",
                source_url="https://firds.esma.europa.eu/firds/DLTINS.zip",
                first_trade_date=now.date() - timedelta(days=2),
            )
        ],
        "esma_firds",
        now=now,
    )
    r = client.get("/v1/public/listings/events")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["data"][0]["event_type"] == "new_listing" and body["data"][0]["isin"] == "FR001400AJ45"
    )
    assert (
        body["venues"]["XPAR"]["region"] == "europe"
        and "not an IPO determination" in body["disclaimer"]
    )
    assert "X-API-Key" not in r.request.headers
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/public/listings/events"]["get"]["security"] == []
    page = client.get("/listings/")
    assert page.status_code == 200 and "/v1/public/listings/events" in client.get("/public.js").text
    assert "not affiliated" in page.text.lower() and 'id="listings-table"' in page.text
