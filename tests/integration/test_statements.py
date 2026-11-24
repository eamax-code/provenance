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


def test_split_adjusted_series_from_a_restating_filing(client, auth, db, monkeypatch):
    """S-02: the ratio comes from a later filing restating a year (12.00 as filed, 3.00 in the
    10-K two years later); older years are adjusted by it, beside the as-filed cells."""
    import hashlib
    from datetime import UTC, date, datetime

    from app.db.models import Company, Filing, FinancialFact

    now, cik = datetime.now(UTC), "0000000778"
    db.add(Company(cik=cik, legal_name="SPLITCO TWO INC", ticker="SPLB",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    # (fiscal year, filed, accession suffix, shares, eps)
    facts = [
        (2017, date(2017, 11, 1), "17", 5_217_242e3, 9.27),
        (2018, date(2018, 11, 1), "18", 4_955_377e3, 12.00),  # as first filed
        (2018, date(2020, 10, 30), "20", 19_821_510e3, 3.00),
    ]  # restated after the split
    for y, filed, suf, shares, eps in facts:
        acc = f"{cik}-{suf}-000001"
        url = f"https://www.sec.gov/Archives/edgar/data/778/{acc.replace('-', '')}/{acc}-index.html"
        db.merge(Filing(cik=cik, accession_number=acc, form_type="10-K", filing_date=filed,
                        source_url=url, first_detected_at=now, quality_status="ok"))  # fmt: skip
        for metric, value, unit in (("shares_basic_weighted", shares, "shares"),
                                    ("eps_basic", eps, "USD/shares")):  # fmt: skip
            db.add(FinancialFact(
                cik=cik, metric=metric, value=value, unit=unit, currency="USD",
                period_start=date(y - 1, 10, 1), period_end=date(y, 9, 30),
                period_type="duration", period_class="annual", fiscal_year=y,
                fiscal_period="FY", form_type="10-K", filed_date=filed, accession_number=acc,
                source_tag="t", source_taxonomy="us-gaap", source_url=url,
                mapping_version="1.5.0", quality_status="ok", derived=False,
                first_detected_at=now, processed_at=now,
                observation_key=hashlib.sha256(f"{metric}{y}{suf}".encode()).hexdigest(),
            ))  # fmt: skip
    db.commit()
    from app.services import statements as st

    # S-02c: not in the reviewed split list: the break is noted, nothing is adjusted
    body = client.get(f"/v1/companies/{cik}/statements/income", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    assert rows["eps_basic"]["split_adjusted"] is None
    assert rows["eps_basic"]["split_break"]["reviewed"] is False
    note = rows["eps_basic"]["split_break"]["text"]
    assert note.startswith("The share basis changes here (restated in the 10-K filed")
    monkeypatch.setattr(st, "reviewed_splits", lambda: {(cik, "4:1"): "2020-08-31"})
    body = client.get(f"/v1/companies/{cik}/statements/income", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    assert rows["eps_basic"]["split_break"]["reviewed"] is True
    adj = rows["eps_basic"]["split_adjusted"]
    assert adj["ratio"] == "4:1" and adj["derived"] is True
    assert adj["values"] == [2.3175, 3.0]  # FY2017 9.27 / 4; FY2018 as restated
    assert (
        adj["source"]["filed_date"] == "2020-10-30" and "12 as filed" in adj["source"]["evidence"]
    )
    assert rows["shares_basic_weighted"]["split_adjusted"]["values"][0] == 5_217_242e3 * 4
    assert [c["value"] for c in rows["eps_basic"]["cells"]] == [9.27, 3.0]  # as filed stays
    assert any("Split-adjusted values (4:1)" in n for n in body["notes"])


def test_a_reviewed_split_counts_when_income_swings_too(db):
    """S-02b (2026-11-24): NVIDIA's 10:1 split year (FY2022 to FY2023 columns) has net income
    down 55%, so shares x EPS swings 0.44x and the income guard rejects it. A pair outside the
    guard counts only with a clean ratio in the reviewed split list (each read in the filing's
    own disclosure); a later filing's restatement alone failed the hand-check (7 of 30)."""
    from app.services import statements as st

    keys = ["FY2022", "FY2023"]
    values = {"shares_diluted_weighted": [2_535_000_000, 25_070_000_000],
              "eps_diluted": [3.85, 0.17],
              "net_income": [9_752_000_000, 4_368_000_000]}  # fmt: skip
    assert st.split_breaks(values, keys) == {}
    assert st.split_breaks(values, keys, lambda b, h: False) == {}
    brk = st.split_breaks(values, keys, lambda b, h: ("0001045810", h) in st.reviewed_splits())
    assert brk["eps_diluted"] == {"between": ["FY2022", "FY2023"], "ratio_hint": "10:1"}
    assert ("0001045810", "10:1") in st.reviewed_splits()
    assert ("0000929351", "1:14") not in st.reviewed_splits()  # Starz: 15-to-1, not a clean read
    assert len(st.reviewed_splits()) == 13  # NVIDIA 4:1 (2021) and 10:1 (2024) both


def test_two_splits_compound_and_both_are_named(client, auth, db, monkeypatch):
    """S-02b (2026-11-24, provenance-pm): NVIDIA split 4:1 in 2021 and 10:1 in 2024; flagging the
    10:1 had dropped the 4:1 and the oldest years were divided by 10, not 40. Every split pair is
    named (the latest as split_break, older ones under "earlier") and the adjusted values
    compound the ratios the filings confirm. Here 2:1, then 3:1: the oldest year is divided by 6.
    Older pairs count only when reviewed: the guard alone failed a hand-check of 30 (2 right)."""
    import hashlib
    from datetime import UTC, date, datetime

    from app.db.models import Company, Filing, FinancialFact

    now, cik = datetime.now(UTC), "0000000779"
    db.add(Company(cik=cik, legal_name="TWOSPLITS INC", ticker="TWOS",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    facts = [  # (fiscal year, filed, accession suffix, shares, eps)
        (2016, date(2016, 11, 1), "16", 100e6, 6.00),
        (2017, date(2017, 11, 1), "17", 100e6, 6.00),
        (2017, date(2018, 11, 1), "18", 200e6, 3.00),  # restated for the 2:1
        (2018, date(2018, 11, 1), "18", 200e6, 3.00),
        (2018, date(2020, 11, 1), "20", 600e6, 1.00),  # restated for the 3:1
        (2019, date(2020, 11, 1), "20", 600e6, 1.00),
    ]
    seen = set()
    for y, filed, suf, shares, eps in facts:
        acc = f"{cik}-{suf}-000001"
        url = f"https://www.sec.gov/Archives/edgar/data/779/{acc.replace('-', '')}/{acc}-index.html"
        if acc not in seen:
            seen.add(acc)
            db.add(Filing(cik=cik, accession_number=acc, form_type="10-K", filing_date=filed,
                          source_url=url, first_detected_at=now, quality_status="ok"))  # fmt: skip
        for metric, value, unit in (("shares_basic_weighted", shares, "shares"),
                                    ("eps_basic", eps, "USD/shares")):  # fmt: skip
            db.add(FinancialFact(
                cik=cik, metric=metric, value=value, unit=unit, currency="USD",
                period_start=date(y - 1, 10, 1), period_end=date(y, 9, 30),
                period_type="duration", period_class="annual", fiscal_year=y,
                fiscal_period="FY", form_type="10-K", filed_date=filed, accession_number=acc,
                source_tag="t", source_taxonomy="us-gaap", source_url=url,
                mapping_version="1.5.0", quality_status="ok", derived=False,
                first_detected_at=now, processed_at=now,
                observation_key=hashlib.sha256(f"{metric}{y}{suf}".encode()).hexdigest(),
            ))  # fmt: skip
    db.commit()
    from app.services import statements as st

    # not in the reviewed list: only the latest pair, adjusted by its own ratio (as before)
    body = client.get(f"/v1/companies/{cik}/statements/income", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    plain = rows["eps_basic"]["split_break"]
    assert "earlier" not in plain and plain["split_date"] is None and plain["reviewed"] is False
    assert plain["restated_in"]["filed_date"] == "2020-11-01"  # the filing behind FY2018
    assert plain["text"].startswith("The share basis changes here (restated in the 10-K filed "
                                    "2020-11-01)") and "3:1" not in plain["text"]  # fmt: skip
    assert rows["eps_basic"]["split_adjusted"] is None  # S-02c: unreviewed, never adjusted
    # both splits reviewed: named with their dates, and compounded
    dates = {(cik, "2:1"): "2018-03-01", (cik, "3:1"): "2020-03-02"}
    monkeypatch.setattr(st, "reviewed_splits", lambda: dates)
    body = client.get(f"/v1/companies/{cik}/statements/income", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    brk = rows["eps_basic"]["split_break"]
    assert brk["between"] == ["FY2017", "FY2018"] and brk["ratio_hint"] == "3:1"
    assert brk["earlier"] == [{"between": ["FY2016", "FY2017"], "ratio_hint": "2:1",
                               "split_date": "2018-03-01"}]  # fmt: skip
    assert brk["split_date"] == "2020-03-02"
    assert brk["text"].startswith("3:1 split, March 2020: shares and per-share figures before "
                                  "FY2018 are as originally filed")  # fmt: skip
    assert "An earlier split (2:1, March 2018) also separates FY2016 and FY2017." in brk["text"]
    adj = rows["eps_basic"]["split_adjusted"]
    assert adj["ratio"] == "3:1" and adj["values"] == [1.0, 1.0, 1.0, 1.0]
    assert [(e["ratio"], e["before"]) for e in adj["earlier"]] == [("2:1", "FY2017")]
    assert rows["shares_basic_weighted"]["split_adjusted"]["values"][0] == 600e6
    assert [c["value"] for c in rows["eps_basic"]["cells"]] == [6.0, 3.0, 1.0, 1.0]  # as filed
