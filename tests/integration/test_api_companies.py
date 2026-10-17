import time

from sqlalchemy import select

from app.db.models import Company


def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert "X-Request-ID" in r.headers


def test_readyz_flags_placeholder_contact_without_leaking_secrets(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "sec_user_agent", "X/1 contact=ops@example.com")
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"
    assert any("placeholder" in p for p in r.json()["configuration"])
    assert settings.api_key_pepper not in r.text


def test_marketing_site_and_llms_txt_are_served(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "not affiliated" in r.text.lower() and "/openapi.json" in r.text and "Pricing" in r.text
    r = client.get("/llms.txt")
    assert r.status_code == 200 and "/v1/companies/{cik}/facts" in r.text
    assert client.get("/v1/companies/search").status_code in (401, 422)  # API routes still win


def test_requires_api_key(client):
    r = client.get("/v1/companies/search?q=aapl")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "missing_api_key" and body["request_id"].startswith("req_")
    assert (
        client.get(
            "/v1/companies/search?q=aapl", headers={"X-API-Key": "prv_test_bogus"}
        ).status_code
        == 401
    )


def test_search_by_ticker_cik_and_name(client, auth, ingested_aapl):
    for q, mt in [
        ("aapl", "ticker"),
        ("320193", "cik"),
        ("0000320193", "cik"),
        ("apple", "name_prefix"),
    ]:
        r = client.get(f"/v1/companies/search?q={q}", headers=auth)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data[0]["cik"] == "0000320193" and data[0]["match_type"] == mt
        assert r.json()["meta"] == {
            "limit": 10,
            "offset": 0,
            "has_more": False,
            "next_offset": None,
            "total_matched": None,
        }


def test_search_validation(client, auth):
    assert client.get("/v1/companies/search", headers=auth).status_code == 422
    r = client.get("/v1/companies/search?q=a&limit=51", headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameter"


def test_company_profile_and_not_found(client, auth, ingested_aapl, settings):
    r = client.get("/v1/companies/320193", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["cik"] == "0000320193" and body["filings_count"] == 6 and body["facts_count"] > 0
    assert body["ingestion_status"] == "complete" and body["source_url"].startswith(
        "https://data.sec.gov/"
    )
    assert client.get("/v1/companies/abc", headers=auth).status_code == 422
    # unknown CIK with on-demand ingestion enabled -> 202 then eventually 404 (SEC returns 404)
    r = client.get("/v1/companies/999", headers=auth)
    assert r.status_code == 202 and r.json()["ingestion_status"] == "processing"
    deadline = time.time() + 5
    while time.time() < deadline:
        r = client.get("/v1/companies/999", headers=auth)
        if r.status_code == 404:
            break
        time.sleep(0.05)
    assert r.status_code == 404 and r.json()["error"]["code"] == "company_not_found"


def test_on_demand_ingestion_for_known_but_unprocessed_company(client, auth, db, tickers_payload):
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(db, tickers_payload)
    db.commit()
    r = client.get("/v1/companies/789019", headers=auth)
    assert r.status_code == 202 and r.json()["ingestion_status"] == "processing"
    deadline = time.time() + 5
    while time.time() < deadline:
        r = client.get("/v1/companies/789019", headers=auth)
        if r.status_code == 200:
            break
        time.sleep(0.05)
    assert r.status_code == 200 and r.json()["filings_count"] == 2


def test_filings_sorted_filtered_paginated(client, auth, ingested_aapl):
    r = client.get("/v1/companies/320193/filings", headers=auth)
    assert r.status_code == 200
    data = r.json()["data"]
    dates = [d["filing_date"] for d in data]
    assert dates == sorted(dates, reverse=True)
    # tie on 2024-05-03 broken by accession desc
    same_day = [d["accession_number"] for d in data if d["filing_date"] == "2024-05-03"]
    assert same_day == sorted(same_day, reverse=True)
    first = data[0]
    assert first["accepted_at"] == "2024-11-01T06:01:36Z" and first["source_published_at"] is None
    assert first["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    eight_k = next(d for d in data if d["form_type"] == "8-K")
    assert eight_k["accepted_at"] is None and eight_k["quality_status"] == "partial"

    r = client.get("/v1/companies/320193/filings?form_type=10-q", headers=auth)
    assert {d["form_type"] for d in r.json()["data"]} == {"10-Q"}
    r = client.get("/v1/companies/320193/filings?since=2024-08-01", headers=auth)
    assert (
        all(d["filing_date"] >= "2024-08-01" for d in r.json()["data"])
        and len(r.json()["data"]) == 2
    )
    r = client.get("/v1/companies/320193/filings?limit=2", headers=auth)
    assert r.json()["meta"] == {
        "limit": 2,
        "offset": 0,
        "has_more": True,
        "next_offset": 2,
        "total_matched": None,
    }
    r2 = client.get("/v1/companies/320193/filings?limit=2&offset=2", headers=auth)
    assert r2.json()["data"][0]["accession_number"] != r.json()["data"][0]["accession_number"]
    assert client.get("/v1/companies/320193/filings?limit=101", headers=auth).status_code == 422
    assert client.get("/v1/companies/1/filings", headers=auth).status_code == 404


def test_facts_annual_default_with_provenance(client, auth, ingested_aapl):
    r = client.get("/v1/companies/320193/facts?metric=revenue", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapping_version"] == "1.0.0"
    data = body["data"]
    assert [d["period_end"] for d in data] == ["2024-09-28", "2023-09-30"]
    latest = data[0]
    assert latest["value"] == 391035000000 and isinstance(latest["value"], int)
    for field in (
        "unit",
        "period_end",
        "source_tag",
        "source_url",
        "mapping_version",
        "accession_number",
        "filed_date",
        "first_detected_at",
        "processed_at",
    ):
        assert latest[field]
    assert (
        latest["period_type"] == "duration"
        and latest["period_class"] == "annual"
        and latest["derived"] is False
    )
    # FY2023 appears in two filings; default view returns the latest-filed one with revision info
    fy23 = data[1]
    assert fy23["accession_number"] == "0000320193-24-000123" and fy23["revision_count"] == 2


def test_facts_all_observations_exposes_restatements_and_alternate_tags(
    client, auth, ingested_aapl
):
    r = client.get(
        "/v1/companies/320193/facts?metric=revenue&include_all_observations=true", headers=auth
    )
    data = r.json()["data"]
    fy23 = [d for d in data if d["period_end"] == "2023-09-30"]
    assert len(fy23) == 3  # two filings of the preferred tag + the alternate tag
    assert {d["quality_status"] for d in fy23} == {"ok", "ambiguous_mapping"}


def test_facts_quarterly_excludes_ytd_and_derived_opt_in(client, auth, ingested_aapl):
    r = client.get("/v1/companies/320193/facts?metric=revenue&period=quarterly", headers=auth)
    data = r.json()["data"]
    assert all(d["period_class"] == "quarterly" and d["derived"] is False for d in data)
    assert "2024-09-28" not in {d["period_end"] for d in data}
    r = client.get(
        "/v1/companies/320193/facts?metric=revenue&period=quarterly&include_derived=true",
        headers=auth,
    )
    data = r.json()["data"]
    q4 = next(d for d in data if d["period_end"] == "2024-09-28")
    assert (
        q4["derived"] is True
        and q4["quality_status"] == "derived"
        and q4["derivation"]["method"] == "subtraction"
    )
    assert q4["value"] == 391035000000 - 296105000000
    assert any("derived" in n.lower() for n in r.json()["notes"])


def test_facts_filters_and_validation(client, auth, ingested_aapl):
    r = client.get("/v1/companies/320193/facts?metric=total_assets&period=all", headers=auth)
    data = r.json()["data"]
    assert all(d["period_type"] == "instant" and d["period_start"] is None for d in data)
    r = client.get(
        "/v1/companies/320193/facts?period=annual&from=2024-01-01&to=2024-12-31", headers=auth
    )
    assert {d["period_end"] for d in r.json()["data"]} == {"2024-09-28"}
    assert {d["metric"] for d in r.json()["data"]} == {
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
        "operating_cash_flow",
    }
    r = client.get("/v1/companies/320193/facts?metric=ebitda", headers=auth)
    assert r.status_code == 422 and "metric must be one of" in r.json()["error"]["message"]
    assert client.get("/v1/companies/320193/facts?period=monthly", headers=auth).status_code == 422
    r = client.get("/v1/companies/320193/facts?limit=2&period=all", headers=auth)
    assert r.json()["meta"]["has_more"] is True and r.json()["meta"]["next_offset"] == 2


def test_facts_invalid_source_value_is_null_not_zero(client, auth, ingested_aapl):
    r = client.get(
        "/v1/companies/320193/facts?metric=net_income&include_all_observations=true", headers=auth
    )
    bad = [d for d in r.json()["data"] if d["quality_status"] == "invalid_source_value"]
    assert len(bad) == 1 and bad[0]["value"] is None


def test_freshness_endpoint(client, auth, ingested_aapl, db):
    r = client.get("/v1/companies/320193/freshness", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["last_successful_fetch_at"]
    lf = body["latest_filing"]
    assert lf["accession_number"] == "0000320193-24-000123"
    assert lf["publication_to_detection_seconds"] is None  # never inferred
    assert (
        lf["acceptance_to_detection_seconds"] is not None and lf["processing_seconds"] is not None
    )
    assert lf["source_date_age_seconds"] > 0
    assert any("date-only" in n for n in body["notes"])
    assert body["ingestion"]["last_run_status"] == "succeeded"


def test_freshness_without_precise_timestamp_has_null_latency(
    client, auth, db, sec_client, fake_sec, submissions_aapl
):
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    recent["acceptanceDateTime"] = [""] * len(recent["accessionNumber"])
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, "filings": {"recent": recent}},
    )
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "320193")
    body = client.get("/v1/companies/320193/freshness", headers=auth).json()
    assert body["latest_filing"]["accepted_at"] is None
    assert body["latest_filing"]["acceptance_to_detection_seconds"] is None
    assert body["status"] == "partial"


def test_freshness_stale_status(client, auth, ingested_aapl, db):
    from datetime import UTC, datetime, timedelta

    c = db.scalar(select(Company).where(Company.cik == "0000320193"))
    c.last_successful_fetch_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()
    body = client.get("/v1/companies/320193/freshness", headers=auth).json()
    assert body["status"] == "stale"


def test_explorer_app_is_served(client):
    r = client.get("/app/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="app"' in r.text and "/app/app.js" in r.text and "not affiliated" in r.text
    js = client.get("/app/app.js")
    assert js.status_code == 200 and "/v1/companies/search" in js.text and "X-API-Key" in js.text
    assert "localStorage" in js.text
    css = client.get("/app/app.css")
    assert css.status_code == 200 and "prefers-color-scheme" in css.text
