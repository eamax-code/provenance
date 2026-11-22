"""X-02: GET /v1/companies/{cik}/statements/{statement} (docs/api-contracts-explorer.md)."""

from __future__ import annotations

import json
from decimal import Decimal

CIK = "320193"


def _rows(body):
    return {r["metric"]: r for r in body["rows"]}


def test_income_statement_matches_facts_cell_for_cell(client, auth, ingested_aapl):
    body = client.get(f"/v1/companies/{CIK}/statements/income", headers=auth).json()
    assert body["statement"] == "income" and body["period"] == "annual"
    assert [c["key"] for c in body["columns"]] == ["FY2023", "FY2024"]  # oldest first
    rows = _rows(body)
    for metric in ("revenue", "operating_income", "net_income"):
        facts = client.get(f"/v1/companies/{CIK}/facts?metric={metric}&period=annual",
                           headers=auth).json()["data"]  # fmt: skip
        by_end = {f["period_end"]: f for f in facts}
        for cell in rows[metric]["cells"]:
            f = by_end[cell["period_end"]]
            assert Decimal(str(cell["value"])) == Decimal(str(f["value"]))
            assert cell["accession_number"] == f["accession_number"]
            assert cell["source_url"].startswith("https://www.sec.gov/Archives/")
            assert cell["source_tag"] and cell["mapping_version"] and cell["quality_status"]
    margin = rows["operating_margin"]
    assert margin["derived"] and margin["formula"] == "Operating income / Revenue"
    last = margin["cells"][-1]
    assert last["value"] == 31.5 and last["unit"] == "%" and len(last["inputs"]) == 2
    assert "gross_margin" not in rows  # no gross profit in the fixture: no row, never zeros
    text = json.dumps(body)
    assert "first_detected" not in text and "data.sec.gov" not in text


def test_as_of_and_other_statements(client, auth, ingested_aapl):
    old = client.get(f"/v1/companies/{CIK}/statements/income?as_of=2024-06-30",
                     headers=auth).json()  # fmt: skip
    assert [c["key"] for c in old["columns"]] == ["FY2023"] and old["as_of"] == "2024-06-30"
    bal = client.get(f"/v1/companies/{CIK}/statements/balance", headers=auth).json()
    assert "total_assets" in _rows(bal)
    cf = client.get(f"/v1/companies/{CIK}/statements/cash_flow", headers=auth).json()
    assert "operating_cash_flow" in _rows(cf) and "free_cash_flow" not in _rows(cf)  # no capex
    q = client.get(f"/v1/companies/{CIK}/statements/income?period=quarterly&periods=8",
                   headers=auth).json()  # fmt: skip
    assert [c["key"] for c in q["columns"]] == ["Q1 FY2024", "Q2 FY2024", "Q3 FY2024", "Q4 FY2024"]
    q4 = _rows(q)["revenue"]["cells"][-1]  # Q4 = FY - 9M, marked derived
    assert q4["derived"] and Decimal(str(q4["value"])) == Decimal("94930000000")


def test_bad_requests(client, auth, ingested_aapl):
    assert client.get(f"/v1/companies/{CIK}/statements/equity", headers=auth).status_code == 422
    r = client.get(f"/v1/companies/{CIK}/statements/income?periods=30", headers=auth)
    assert r.status_code == 422 and "at most 20" in r.json()["error"]["message"]
    assert client.get("/v1/companies/9999999/statements/income", headers=auth).status_code == 404
