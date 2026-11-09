"""Company metadata from the submissions and the one-page overview (issue #9)."""

from __future__ import annotations

import json

from app.services.ingestion import parse_metadata

AMAZON_FIELDS = {
    "ownerOrg": "07 Trade & Services",
    "ein": "911646860",
    "lei": None,
    "website": "",
    "investorWebsite": "",
    "category": "Non-accelerated filer<br>Smaller reporting company",
    "addresses": {
        "mailing": {"street1": "410 TERRY AVENUE NORTH", "street2": None, "city": "SEATTLE",
                    "stateOrCountry": "WA", "zipCode": "98109", "isForeignLocation": 0},
        "business": {"street1": "1 Main St", "city": "Toronto", "stateOrCountry": "A6",
                     "zipCode": "M5V", "isForeignLocation": 1,
                     "stateOrCountryDescription": "Ontario, Canada"},
    },
    "phone": "2062661000",
    "tickers": ["AMZN", ""],
    "exchanges": ["Nasdaq"],
    "insiderTransactionForIssuerExists": 1,
    "insiderTransactionForOwnerExists": 0,
}  # fmt: skip


def test_metadata_is_parsed_from_the_submissions():
    meta = parse_metadata(AMAZON_FIELDS)
    assert meta["filer_category"] == "Non-accelerated filer; Smaller reporting company"
    assert meta["sec_office"] == "07 Trade & Services" and meta["ein"] == "911646860"
    assert meta["lei"] is None and meta["website"] is None  # empty strings are not data
    mailing = json.loads(meta["mailing_address"])
    assert mailing["city"] == "SEATTLE" and mailing["country"] == "United States"
    assert json.loads(meta["business_address"])["country"] == "Ontario, Canada"
    assert json.loads(meta["tickers"]) == ["AMZN"]
    assert meta["insider_filings_as_issuer"] is True and meta["insider_filings_as_owner"] is False
    assert parse_metadata({"ein": "000000000"})["ein"] is None


def test_ingestion_stores_metadata(client, auth, db, sec_client, fake_sec, submissions_aapl):
    from app.services.ingestion import ingest_company

    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, **AMAZON_FIELDS},
    )
    ingest_company(db, sec_client, "320193")
    body = client.get("/v1/companies/320193", headers=auth).json()
    assert body["filer_category"].startswith("Non-accelerated")
    assert body["mailing_address"]["street1"] == "410 TERRY AVENUE NORTH"
    assert body["tickers"] == ["AMZN"] and body["phone"] == "2062661000"


def test_overview_has_every_section_and_no_source_api_links(client, db, ingested_aapl):
    from app.services import marts

    marts.build_company_marts(db)
    marts.build_financial_marts(db)
    r = client.get("/v1/public/companies/320193/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("company", "summary", "history", "key_figures", "years", "filings",
                "filing_activity", "leadership", "peers", "listings", "notes"):  # fmt: skip
        assert key in body, key
    assert body["company"]["display_name"] == "Apple Inc."
    assert body["company"]["fiscal_year_end_month"] == "September"
    assert body["years"] and body["years"][-1]["fiscal_label"].startswith("FY")
    assert body["key_figures"][0]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert body["filings"] and all(f["source_url"].startswith("https://www.sec.gov/")
                                   for f in body["filings"])  # fmt: skip
    text = r.text
    for hidden in ("data.sec.gov", "first_detected_at", "source_updated_at", "api.gleif"):
        assert hidden not in text, hidden
    assert client.get("/v1/public/companies/789019/overview").status_code == 404  # not showcase
    assert client.get("/v1/public/companies/abc/overview").status_code == 422


def test_design_prototypes_are_served(client):
    for v in ("a", "b", "c"):
        r = client.get(f"/companies/0000320193?v={v}")
        assert r.status_code == 200 and "/companies/poc/common.js" in r.text, v
        assert 'aria-current="page"' in r.text
    assert "common.js" not in client.get("/companies/0000320193?v=z").text  # the current page
    js = client.get("/companies/poc/common.js").text
    assert "/v1/public/companies/" in js and "/overview" in js
