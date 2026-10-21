from datetime import UTC, date, datetime, timedelta

from app.services.markets import ingest
from app.services.markets.records import ListingRecord

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def _seed(db):
    ingest.ensure_market(
        db,
        "XPAR",
        "Euronext Paris",
        "FR",
        "europe",
        "esma_firds",
        "https://registers.esma.europa.eu/",
    )
    ingest.ensure_market(
        db, "XLON", "London Stock Exchange", "GB", "uk", "fca_firds", "https://data.fca.org.uk/"
    )
    ingest.ensure_market(
        db, "XTSE", "Toronto Stock Exchange", "CA", "canada", "tsx", "https://www.tsx.com/"
    )
    db.commit()
    recs = [
        ListingRecord(
            isin="FR0000120271",
            mic="XPAR",
            issuer_name="TotalEnergies SE",
            issuer_lei="529900S21EQ1BO4ESM68",
            symbol="TTE",
            source="esma_firds",
            source_url="https://registers.esma.europa.eu/x",
            currency="EUR",
            first_trade_date=date(1990, 1, 2),
        ),
        ListingRecord(
            isin="FR0000120271",
            mic="XLON",
            issuer_name="TotalEnergies SE",
            issuer_lei="529900S21EQ1BO4ESM68",
            symbol="TTE",
            source="fca_firds",
            source_url="https://data.fca.org.uk/x",
            currency="GBP",
            first_trade_date=date(1995, 5, 5),
        ),
        ListingRecord(
            isin="FR001400AJ45",
            mic="XPAR",
            issuer_name="Exosens",
            issuer_lei="969500ABCDEFGHIJ1234",
            source="esma_firds",
            source_url="https://registers.esma.europa.eu/y",
            currency="EUR",
            first_trade_date=NOW.date() - timedelta(days=2),
        ),
        ListingRecord(
            isin="CA0679011084",
            mic="XTSE",
            issuer_name="Barrick Gold Corp",
            issuer_lei=None,
            symbol="ABX",
            source="tsx",
            source_url="https://www.tsx.com/x",
            currency="CAD",
            first_trade_date=date(1985, 1, 1),
        ),
    ]
    ingest.ingest_records(db, recs, "mixed", now=NOW)
    ingest.ingest_records(
        db,
        [
            ListingRecord(
                isin="CA0679011084",
                mic="XTSE",
                issuer_name="Barrick Gold Corp",
                symbol="ABX",
                source="tsx",
                source_url="https://www.tsx.com/x",
                currency="CAD",
                first_trade_date=date(1985, 1, 1),
                termination_date=NOW.date(),
            )
        ],
        "tsx",
        now=NOW + timedelta(hours=1),
    )


def test_markets_require_key_and_list_counts(client, auth, db):
    _seed(db)
    assert client.get("/v1/markets/").status_code == 401
    r = client.get("/v1/markets/", headers=auth)
    assert r.status_code == 200, r.text
    by_mic = {m["mic"]: m for m in r.json()["data"]}
    assert by_mic["XPAR"]["instruments_listed"] == 2 and by_mic["XTSE"]["instruments_delisted"] == 1
    assert by_mic["XLON"]["region"] == "uk" and by_mic["XLON"]["source_url"].startswith(
        "https://data.fca.org.uk"
    )
    assert any("not an IPO determination" in n for n in r.json()["notes"])


def test_instruments_filters_and_search(client, auth, db):
    _seed(db)
    r = client.get("/v1/markets/instruments?region=europe&status=listed", headers=auth)
    assert {(i["isin"], i["mic"]) for i in r.json()["data"]} == {
        ("FR0000120271", "XPAR"),
        ("FR001400AJ45", "XPAR"),
    }
    assert r.json()["data"][0]["isin"] == "FR001400AJ45"  # newest first-trade date first
    assert (
        client.get("/v1/markets/instruments?q=total", headers=auth).json()["data"][0]["issuer_name"]
        == "TotalEnergies SE"
    )
    assert len(client.get("/v1/markets/instruments?q=TTE", headers=auth).json()["data"]) == 2
    assert (
        client.get("/v1/markets/instruments?country=ca", headers=auth).json()["data"][0]["status"]
        == "delisted"
    )
    assert (
        client.get("/v1/markets/instruments?first_trade_since=2026-01-01", headers=auth).json()[
            "data"
        ][0]["isin"]
        == "FR001400AJ45"
    )
    assert (
        client.get("/v1/markets/instruments?limit=1", headers=auth).json()["meta"]["has_more"]
        is True
    )
    assert client.get("/v1/markets/instruments?status=bogus", headers=auth).status_code == 422


def test_instrument_detail_and_issuer(client, auth, db):
    _seed(db)
    r = client.get("/v1/markets/instruments/fr0000120271", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert [x["mic"] for x in body["listings"]] == ["XLON", "XPAR"] and body["issuer"][
        "lei"
    ] == "529900S21EQ1BO4ESM68"
    assert body["listings"][0]["source_url"] and body["listings"][0]["first_detected_at"].endswith(
        "Z"
    )
    assert (
        client.get("/v1/markets/instruments/FR0000120272", headers=auth).status_code == 422
    )  # bad check digit
    assert client.get("/v1/markets/instruments/DE0005140008", headers=auth).status_code == 404
    r = client.get("/v1/markets/issuers/529900S21EQ1BO4ESM68", headers=auth)
    assert r.status_code == 200 and len(r.json()["listings"]) == 2
    assert client.get("/v1/markets/issuers/0000000000000000000X", headers=auth).status_code == 404


def test_events_listing_and_filters(client, auth, db):
    _seed(db)
    r = client.get("/v1/markets/events", headers=auth)
    assert r.status_code == 200
    types = {e["event_type"] for e in r.json()["data"]}
    assert types == {"new_listing", "delisting"}
    new = client.get("/v1/markets/events?type=new_listing", headers=auth).json()["data"]
    assert (
        new[0]["isin"] == "FR001400AJ45"
        and new[0]["details"]["first_listing_for_issuer_in_our_data"] is True
    )
    assert (
        client.get("/v1/markets/events?region=canada", headers=auth).json()["data"][0]["event_type"]
        == "delisting"
    )
    assert client.get("/v1/markets/events?type=merger", headers=auth).status_code == 422
    assert (
        client.get(f"/v1/markets/events?since={NOW.date().isoformat()}", headers=auth).json()[
            "data"
        ][0]["event_type"]
        == "delisting"
    )


def test_markets_in_openapi_and_metered(client, auth, db):
    _seed(db)
    client.get("/v1/markets/events", headers=auth)
    spec = client.get("/openapi.json").json()
    for path in (
        "/v1/markets/",
        "/v1/markets/instruments",
        "/v1/markets/instruments/{isin}",
        "/v1/markets/events",
        "/v1/markets/issuers/{lei}",
    ):
        assert spec["paths"][path]["get"]["security"] == [{"ApiKeyAuth": []}], path
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert "/v1/markets/events" in usage["requests_by_route"]
