def _ingest_both(db, sec_client, tickers_payload=None):
    from app.services.ingestion import import_ticker_mapping, ingest_company

    if tickers_payload is not None:
        import_ticker_mapping(db, tickers_payload)
        db.commit()
    ingest_company(db, sec_client, "320193")
    ingest_company(db, sec_client, "789019")


def test_company_list_filters_and_pagination(client, auth, db, sec_client, tickers_payload):
    _ingest_both(db, sec_client, tickers_payload)
    r = client.get("/v1/companies", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total_matched"] == 5 and len(body["data"]) == 5
    assert [c["legal_name"] for c in body["data"]][:2] == [
        "Alphabet Inc.",
        "Apple Inc.",
    ]  # name order
    ingested = client.get("/v1/companies?ingested=true", headers=auth).json()["data"]
    assert {c["cik"] for c in ingested} == {"0000320193", "0000789019"}
    assert all(c["ingestion_status"] == "complete" for c in ingested)
    assert (
        client.get("/v1/companies?exchange=nyse", headers=auth).json()["data"][0]["ticker"]
        == "BRK-B"
    )
    assert (
        client.get("/v1/companies?sic=7372", headers=auth).json()["data"][0]["cik"] == "0000789019"
    )
    assert (
        client.get("/v1/companies?state=CA", headers=auth).json()["data"][0]["cik"] == "0000320193"
    )
    page = client.get("/v1/companies?limit=2&offset=2", headers=auth).json()
    assert (
        len(page["data"]) == 2
        and page["meta"]["has_more"] is True
        and page["meta"]["next_offset"] == 4
    )
    by_cik = client.get("/v1/companies?sort=cik", headers=auth).json()["data"]
    assert by_cik[0]["cik"] == "0000320193"
    assert client.get("/v1/companies?limit=500", headers=auth).status_code == 422
    assert client.get("/v1/companies?sort=revenue", headers=auth).status_code == 422
    assert client.get("/v1/companies").status_code == 401


def test_screen_ranks_one_metric_across_companies(client, auth, db, sec_client):
    _ingest_both(db, sec_client)
    r = client.get("/v1/facts/screen?metric=total_assets&year=2024", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["data"]
    assert [x["cik"] for x in rows] == ["0000789019", "0000320193"]  # MSFT 512.2B > AAPL 365.0B
    top = rows[0]
    assert (
        top["value"] == 512163000000 and top["unit"] == "USD" and top["period_end"] == "2024-06-30"
    )
    assert top["legal_name"] == "MICROSOFT CORP" and top["ticker"] == "MSFT"
    for field in (
        "source_url",
        "source_tag",
        "accession_number",
        "mapping_version",
        "quality_status",
        "filed_date",
    ):
        assert top[field]
    assert body["meta"]["total_matched"] == 2 and body["year"] == 2024 and body["unit"] == "USD"
    assert any("period_end" in n for n in body["notes"])
    asc = client.get(
        "/v1/facts/screen?metric=total_assets&year=2024&order=asc", headers=auth
    ).json()["data"]
    assert asc[0]["cik"] == "0000320193"


def test_screen_excludes_ambiguous_and_other_units(client, auth, db, sec_client):
    _ingest_both(db, sec_client)
    rev = client.get("/v1/facts/screen?metric=revenue&year=2024", headers=auth).json()["data"]
    assert [x["cik"] for x in rev] == [
        "0000320193"
    ]  # MSFT revenue tags disagree -> ambiguous, excluded
    assert rev[0]["value"] == 391035000000 and rev[0]["period_end"] == "2024-09-28"
    assert (
        client.get("/v1/facts/screen?metric=revenue&year=2024&unit=EUR", headers=auth).json()[
            "data"
        ]
        == []
    )
    assert (
        client.get("/v1/facts/screen?metric=revenue&year=2023", headers=auth).json()["data"][0][
            "period_end"
        ]
        == "2023-09-30"
    )


def test_screen_validation_and_openapi(client, auth, db, sec_client):
    _ingest_both(db, sec_client)
    assert client.get("/v1/facts/screen?metric=ebitda&year=2024", headers=auth).status_code == 422
    assert client.get("/v1/facts/screen?metric=revenue", headers=auth).status_code == 422
    assert client.get("/v1/facts/screen?metric=revenue&year=1800", headers=auth).status_code == 422
    assert (
        client.get("/v1/facts/screen?metric=revenue&year=2024&limit=1000", headers=auth).status_code
        == 422
    )
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/facts/screen"]["get"]["security"] == [{"ApiKeyAuth": []}]
    assert spec["paths"]["/v1/companies"]["get"]["security"] == [{"ApiKeyAuth": []}]
