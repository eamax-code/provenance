"""Point-in-time facts: answers use only observations filed by the as_of date."""

from __future__ import annotations

from tests.conftest import REVENUE_ORIGINAL as ORIGINAL
from tests.conftest import REVENUE_RESTATED as RESTATED
from tests.conftest import REVENUE_TAG as TAG


def _fy(data, end):
    return [d for d in data if d["period_end"] == end and d["source_tag"] == TAG]


def test_as_of_returns_value_known_before_restatement(client, auth, restated_aapl):
    url = "/v1/companies/320193/facts?metric=revenue"
    before = client.get(url + "&as_of=2024-01-15", headers=auth).json()
    fy23 = _fy(before["data"], "2023-09-30")
    assert len(fy23) == 1
    assert fy23[0]["value"] == ORIGINAL
    assert fy23[0]["accession_number"] == "0000320193-23-000106"
    assert fy23[0]["revision_count"] == 1
    assert not _fy(before["data"], "2024-09-28")  # FY2024 not filed yet
    assert before["as_of"] == "2024-01-15"
    assert any("Point in time as of 2024-01-15" in n for n in before["notes"])

    after = client.get(url + "&as_of=2024-11-01", headers=auth).json()
    fy23 = _fy(after["data"], "2023-09-30")
    assert fy23[0]["value"] == RESTATED
    assert fy23[0]["accession_number"] == "0000320193-24-000123"
    assert fy23[0]["revision_count"] == 2
    assert _fy(after["data"], "2024-09-28")

    latest = client.get(url, headers=auth).json()
    assert latest["as_of"] is None
    assert _fy(latest["data"], "2023-09-30")[0]["value"] == RESTATED


def test_as_of_all_observations_hides_later_filings(client, auth, restated_aapl):
    r = client.get(
        "/v1/companies/320193/facts?metric=revenue&include_all_observations=true&as_of=2023-12-31",
        headers=auth,
    )
    filed = {d["filed_date"] for d in r.json()["data"]}
    assert filed and max(filed) <= "2023-12-31"


def test_as_of_derived_quarters_use_only_known_observations(client, auth, restated_aapl):
    url = "/v1/companies/320193/facts?metric=revenue&period=quarterly&include_derived=true"
    before = client.get(url + "&as_of=2024-10-31", headers=auth).json()["data"]
    assert "2024-09-28" not in {d["period_end"] for d in before}  # needs the FY2024 10-K
    after = client.get(url + "&as_of=2024-11-01", headers=auth).json()["data"]
    q4 = next(d for d in after if d["period_end"] == "2024-09-28")
    assert q4["derived"] is True and q4["value"] == 391_035_000_000 - 296_105_000_000


def test_screen_as_of(client, auth, restated_aapl):
    url = "/v1/facts/screen?metric=revenue&year=2023"
    assert client.get(url + "&as_of=2023-11-02", headers=auth).json()["data"] == []
    body = client.get(url + "&as_of=2024-01-15", headers=auth).json()
    assert body["as_of"] == "2024-01-15"
    assert body["data"][0]["value"] == ORIGINAL
    assert any("Point in time" in n for n in body["notes"])
    assert client.get(url, headers=auth).json()["data"][0]["value"] == RESTATED


def test_as_of_rejects_bad_date(client, auth, restated_aapl):
    r = client.get("/v1/companies/320193/facts?as_of=2024-13-01", headers=auth)
    assert r.status_code == 422
