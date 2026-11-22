"""X-01a: the keyed overview for any company, with provenance card fields and TTM."""

from __future__ import annotations

import json

CIK = "320193"


def test_keyed_overview_for_any_company_with_card_fields(client, auth, ingested_aapl):
    r = client.get(f"/v1/companies/{CIK}/overview", headers=auth)
    assert r.status_code == 200 and "private" in r.headers["cache-control"]
    body = r.json()
    assert body["company"]["cik"] == "0000320193"
    kf = {k["metric"]: k for k in body["key_figures"]}
    rev = kf["revenue"]
    assert rev["source_tag"] and rev["mapping_version"] and rev["accession_number"]
    assert rev["quality_status"] == "ok" and rev["source_url"].startswith(
        "https://www.sec.gov/Archives/"
    )
    year = body["years"][-1]
    assert year["provenance"]["revenue"]["source_tag"] == rev["source_tag"]
    assert isinstance(year["sources"]["revenue"], str)  # unchanged shape for existing readers
    cells = [c for row in body["statements"].get("rows", []) for c in row.get("cells", []) if c]
    assert all("source_tag" in c and "mapping_version" in c for c in cells)
    assert "ttm" not in rev  # the latest quarters are more than 15 months old
    text = json.dumps(body)
    assert "first_detected" not in text and "data.sec.gov" not in text


def test_ttm_sums_the_last_four_quarters_and_lists_them(client, auth, ingested_aapl):
    body = client.get(f"/v1/companies/{CIK}/overview?as_of=2024-12-31", headers=auth).json()
    rev = {k["metric"]: k for k in body["key_figures"]}["revenue"]
    ttm = rev["ttm"]
    assert ttm["value"] == 391035000000 and ttm["derived"] and len(ttm["inputs"]) == 4
    assert ttm["formula"] == "sum of the last 4 quarters" and ttm["inputs"][-1]["derived"]
    assert ttm["period_end"] == "2024-09-28"


def test_keyed_overview_errors(client, auth, ingested_aapl):
    assert client.get("/v1/companies/9999999/overview", headers=auth).status_code == 404
    r = client.get(f"/v1/companies/{CIK}/overview?as_of=2099-01-01", headers=auth)
    assert r.status_code == 422
