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


def test_values_are_numbers_and_cover_dates_join_their_quarter(client, auth, ingested_aapl):
    body = client.get(f"/v1/companies/{CIK}/statements/income", headers=auth).json()
    cell = next(c for c in _rows(body)["revenue"]["cells"] if c)
    assert isinstance(cell["value"], (int, float))  # a JSON number, never "391035000000.000000"
    bal = client.get(f"/v1/companies/{CIK}/statements/balance?period=quarterly",
                     headers=auth).json()  # fmt: skip
    keys = [c["key"] for c in bal["columns"]]
    assert len(keys) == len(set(keys))  # a cover-page date never makes a column of its own


def test_a_successor_continues_with_its_predecessors_cells(client, auth, db, ingested_aapl):
    from datetime import UTC, date, datetime

    from app.db.models import Company, RegistrantSuccession

    db.add(Company(cik="0002999999", legal_name="Apple Holdings Example Inc", ticker=None,
                   source_url="https://www.sec.gov/", first_detected_at=datetime.now(UTC),
                   quality_status="ok"))  # fmt: skip
    db.add(RegistrantSuccession(
        predecessor_cik="0000320193", successor_cik="0002999999",
        effective_date=date(2026, 7, 1), evidence_accession="0002999999-26-000001",
        evidence_form="8-K12B", match_method="holding_company_reorganization", confidence="high",
    ))  # fmt: skip
    db.commit()
    body = client.get("/v1/companies/2999999/statements/income", headers=auth).json()
    cell = next(c for c in _rows(body)["revenue"]["cells"] if c)
    assert cell["predecessor"] and cell["registrant_cik"] == "0000320193"
    assert "predecessor registrant" in cell["registrant_label"]


def test_split_break_on_the_statement(client, auth, db):
    import hashlib
    from datetime import UTC, date, datetime

    from app.db.models import Company, Filing, FinancialFact

    now, cik = datetime.now(UTC), "0000000777"
    db.add(Company(cik=cik, legal_name="SPLITCO INC", ticker="SPLT", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now, quality_status="ok"))  # fmt: skip
    years = {2017: (5_217_242e3, 9.27, 48_351e6), 2018: (19_821_510e3, 3.00, 59_531e6)}
    for y, (shares, eps, income) in years.items():
        acc = f"{cik}-{y % 100}-000001"
        url = f"https://www.sec.gov/Archives/edgar/data/777/{acc.replace('-', '')}/{acc}-index.html"
        db.add(Filing(cik=cik, accession_number=acc, form_type="10-K", filing_date=date(y, 11, 1),
                      source_url=url, first_detected_at=now, quality_status="ok"))  # fmt: skip
        values = (("shares_basic_weighted", shares, "shares"), ("eps_basic", eps, "USD/shares"),
                  ("net_income", income, "USD"))  # fmt: skip
        for metric, value, unit in values:
            db.add(FinancialFact(
                cik=cik, metric=metric, value=value, unit=unit, currency="USD",
                period_start=date(y - 1, 10, 1), period_end=date(y, 9, 30), period_type="duration",
                period_class="annual", fiscal_year=y, fiscal_period="FY", form_type="10-K",
                filed_date=date(y, 11, 1), accession_number=acc, source_tag="t",
                source_taxonomy="us-gaap", source_url=url, mapping_version="1.5.0",
                quality_status="ok", derived=False, first_detected_at=now, processed_at=now,
                observation_key=hashlib.sha256(f"{metric}{y}".encode()).hexdigest(),
            ))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{cik}/statements/income", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    brk = rows["eps_basic"]["split_break"]
    assert brk["between"] == ["FY2017", "FY2018"] and brk["ratio_hint"] == "4:1"
    assert rows["shares_basic_weighted"]["split_break"] == brk
    assert rows["net_income"]["split_break"] is None
    assert brk["text"] in body["notes"] and "not adjusted" in brk["text"]
    assert [c["value"] for c in rows["eps_basic"]["cells"]] == [9.27, 3.0]  # never adjusted
