"""Q-04: dividends declared per share (docs/contracts/dividends.md)."""

from __future__ import annotations

import copy

from sqlalchemy import func, select

from app.db.models import DividendFact

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def _with_dps(payload: dict) -> dict:
    """The fixture's revenue observations again as diluted EPS and as dividends declared per
    share (same periods, forms and filings), so dividends and statements share their columns
    and the statements have a per-share row to mark split columns on."""
    p = copy.deepcopy(payload)
    gaap = p["facts"]["us-gaap"]
    rev = gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]
    for tag, scale in (("EarningsPerShareDiluted", 4e-11), ("CommonStockDividendsPerShareDeclared",
                                                            6e-12)):  # fmt: skip
        obs = copy.deepcopy(rev)
        for o in obs:
            o["val"] = round(o["val"] * scale, 2)
        gaap[tag] = {"units": {"USD/shares": obs}}
    return p


def _ingest(db, sec_client):
    from app.services.ingestion import ingest_company

    return ingest_company(db, sec_client, "320193")


def test_ingest_stores_dividends_with_the_facts(db, sec_client, fake_sec, facts_aapl):
    """A company's ingest stores dividends per share from the same payload, in the same run;
    a later 10-Q's value appears on the next ingest (no gap after the bulk load)."""
    fake_sec.add(URL, facts_aapl)
    _ingest(db, sec_client)
    assert db.scalar(select(func.count()).select_from(DividendFact)) == 0
    payload = _with_dps(facts_aapl)
    newest = max(payload["facts"]["us-gaap"]["CommonStockDividendsPerShareDeclared"]["units"]
                 ["USD/shares"], key=lambda o: o["filed"])  # fmt: skip
    fake_sec.add(URL, payload)
    _ingest(db, sec_client)
    rows = list(db.scalars(select(DividendFact)))
    assert rows and {r.metric for r in rows} == {"dividends_per_share"}
    assert any(r.accession_number == newest["accn"] for r in rows)
    assert {r.period_class for r in rows} >= {"annual", "quarterly"}


def test_dividend_columns_are_the_statements_columns(client, auth, db, sec_client, fake_sec,
                                                     facts_aapl, monkeypatch):  # fmt: skip
    """PM condition 2: a dividend column is the income statement's column for the same period
    (key, end, fiscal year), annual and quarterly, and its split basis is the statements' per
    column rule: the cells the statements mark pre-split are the ones with a factor above 1."""
    from app.services import statements as st

    fake_sec.add(URL, _with_dps(facts_aapl))
    _ingest(db, sec_client)
    for period, n in (("annual", 12), ("quarterly", 20)):
        div = client.get(f"/v1/companies/320193/dividends?period={period}&periods={n}",
                         headers=auth).json()  # fmt: skip
        stm = client.get(f"/v1/companies/320193/statements/income?period={period}&periods={n}",
                         headers=auth).json()  # fmt: skip
        keys = {c["period_end"]: c["key"] for c in stm["columns"]}
        assert div["data"], period
        shared = [r for r in div["data"] if r["period_end"] in keys]
        assert len(shared) >= min(4, len(div["data"])), period
        for r in shared:
            assert r["period_label"] == keys[r["period_end"]], (period, r["period_end"])
    # a split between the fixture's 10-Ks: the same columns are pre-split on both
    split = {"first": st.date_span("2024-06-15")[0], "last": st.date_span("2024-06-15")[1],
             "factor": 4.0, "hint": "4:1", "date": "2024-06-15", "form": "8-K",
             "filed": "2024-06-15", "disclosure": "a 4:1 split"}  # fmt: skip
    monkeypatch.setattr(st, "dated_splits", lambda: {"0000320193": [split]})
    monkeypatch.setattr(st, "reviewed_splits", lambda: {("0000320193", "4:1"): ("2024-06-15",)})
    q = "period=quarterly&periods=20"  # Q1 and Q2 FY2024 filed before the split, Q3 after
    div = client.get(f"/v1/companies/320193/dividends?{q}", headers=auth).json()
    stm = client.get(f"/v1/companies/320193/statements/income?{q}", headers=auth).json()
    eps = next(r for r in stm["rows"] if r["metric"] == "eps_diluted")
    pre = set((eps["split_break"] or {}).get("pre_split_columns") or [])
    marked = {
        r["period_label"] for r in div["data"] if (r["split_adjusted"] or {}).get("factor", 1) > 1
    }
    assert pre and marked == pre & {r["period_label"] for r in div["data"]}


def test_no_dividend_tag_is_no_rows_and_never_says_none_paid(client, auth, ingested_aapl):
    body = client.get("/v1/companies/320193/dividends", headers=auth).json()
    assert body["data"] == [] and body["notes"]
    assert "pays no dividend" not in " ".join(body["notes"]).lower()


def _fact(model, cik, metric, value, unit, start, end, cls, acc, filed):
    import hashlib
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return model(cik=cik, metric=metric, value=value, unit=unit, currency="USD",
                 period_start=start, period_end=end, period_type="duration", period_class=cls,
                 fiscal_year=end.year, fiscal_period="FY", form_type="10-K", filed_date=filed,
                 accession_number=acc, source_tag="CommonStockDividendsPerShareDeclared"
                 if model is DividendFact else "t", source_taxonomy="us-gaap",
                 source_url=f"https://www.sec.gov/Archives/{acc}", mapping_version="1.5.0",
                 quality_status="ok", derived=False, first_detected_at=now, processed_at=now,
                 observation_key=hashlib.sha256(
                     f"{metric}{acc}{start}{end}".encode()).hexdigest())  # fmt: skip


def test_payout_uses_the_dividends_own_filing_and_special_is_not_given(client, auth, db):
    """Payout ratio: diluted EPS as the dividend's own filing reports it (one share basis: a later
    10-K's EPS after a split would halve it), never over 10 (two share classes); special is null
    on every row until a source marks specials."""
    from datetime import UTC, date, datetime

    from app.db.models import Company, FinancialFact

    cik, now = "0000000901", datetime.now(UTC)
    db.add(Company(cik=cik, legal_name="PAYCO INC", ticker="PAYC", fiscal_year_end="1231",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    y24, y25 = (date(2024, 1, 1), date(2024, 12, 31)), (date(2025, 1, 1), date(2025, 12, 31))
    a24, a25, later = "0000000901-25-000001", "0000000901-26-000001", "0000000901-27-000001"
    db.add_all([
        _fact(DividendFact, cik, "dividends_per_share", 2.0, "USD/shares", *y24, "annual", a24,
              date(2025, 2, 1)),
        _fact(FinancialFact, cik, "eps_diluted", 4.0, "USD/shares", *y24, "annual", a24,
              date(2025, 2, 1)),
        _fact(FinancialFact, cik, "eps_diluted", 2.0, "USD/shares", *y24, "annual", later,
              date(2027, 2, 1)),  # restated after a 2:1 split: not the dividend's basis
        _fact(DividendFact, cik, "dividends_per_share", 50.0, "USD/shares", *y25, "annual", a25,
              date(2026, 2, 1)),
        _fact(FinancialFact, cik, "eps_diluted", 1.0, "USD/shares", *y25, "annual", a25,
              date(2026, 2, 1)),
    ])  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{cik}/dividends", headers=auth).json()
    rows = {r["period_label"]: r for r in body["data"]}
    assert rows["FY2024"]["payout_ratio"]["value"] == 0.5  # 2.00 / 4.00, the same 10-K
    assert [i["accession_number"] for i in rows["FY2024"]["payout_ratio"]["inputs"]] == [a24, a24]
    assert rows["FY2025"]["payout_ratio"] is None  # 50 / 1: two share classes, not a payout
    assert all(r["special"] is None for r in body["data"])
    assert any("special is not given yet" in n for n in body["notes"])


def test_a_derived_quarter_uses_values_as_first_filed(client, auth, db):
    """FY minus nine months from one reporting cycle: a later 10-K restating the year after an
    unreviewed 2:1 split (1.16 -> 0.58) gave a Q4 of -0.29 from the nine months as first filed."""
    from datetime import UTC, date, datetime

    from app.db.models import Company

    cik, now = "0000000902", datetime.now(UTC)
    db.add(Company(cik=cik, legal_name="SPLITLATER INC", ticker="SPLL", fiscal_year_end="1231",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    m, u, s0 = "dividends_per_share", "USD/shares", date(2020, 1, 1)
    db.add_all([
        _fact(DividendFact, cik, m, 0.87, u, s0, date(2020, 9, 30), "ytd", "a-20-1",
              date(2020, 11, 6)),
        _fact(DividendFact, cik, m, 1.16, u, s0, date(2020, 12, 31), "annual", "a-21-1",
              date(2021, 3, 12)),
        _fact(DividendFact, cik, m, 0.58, u, s0, date(2020, 12, 31), "annual", "a-23-1",
              date(2023, 3, 10)),  # restated on the post-split basis
    ])  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{cik}/dividends?period=quarterly", headers=auth).json()
    (q4,) = [r for r in body["data"] if r["period_label"] == "Q4 FY2020"]
    assert q4["derived"] and q4["declared_per_share"] == 0.29
    assert [i["value"] for i in q4["inputs"]] == [1.16, 0.87]


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def test_dividends_response_carries_no_internal_field_or_api_url(client, auth, db, sec_client,
                                                                fake_sec, facts_aapl):  # fmt: skip
    """The rule every new endpoint has: no first_detected_at, source_updated_at or CUSIP, and every
    link a sec.gov/Archives page, in the API and the MCP tool."""
    import json

    fake_sec.add(URL, _with_dps(facts_aapl))
    _ingest(db, sec_client)
    for q in ("period=annual", "period=quarterly&as_of=2024-06-30"):
        body = client.get(f"/v1/companies/320193/dividends?{q}", headers=auth).json()
        assert body["data"]
        raw = json.dumps(body).lower()
        for banned in ("first_detected_at", "source_updated_at", "cusip", "data.sec.gov"):
            assert banned not in raw, (q, banned)
        urls = [v for k, v in _walk(body) if k.endswith("url") and v]
        assert urls and all(u.startswith("https://www.sec.gov/Archives/") for u in urls), urls
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "company_dividends", "arguments": {"cik": "320193"}}}  # fmt: skip
    res = client.post("/mcp", json=rpc).json()["result"]
    assert res["isError"] is False, res
    mcp = json.loads(res["content"][0]["text"])
    assert mcp["data"] and "first_detected" not in json.dumps(mcp)


def test_chat_answers_dividends_with_a_table_never_a_yield(client, auth, db, sec_client,
                                                           fake_sec, facts_aapl):  # fmt: skip
    from app.services.chat_intents import detect

    assert detect("What dividend does Apple pay?") == "dividends"
    assert detect("What is Apple's payout ratio?") == "dividends"
    assert detect("Who are Apple's largest holders?") == "holders"  # unchanged
    fake_sec.add(URL, _with_dps(facts_aapl))
    _ingest(db, sec_client)
    r = client.post("/v1/chat", json={"message": "What dividend does Apple pay?",
                                      "cik": "0000320193"}, headers=auth).json()  # fmt: skip
    assert r["intent"] == "dividends" and r["answered_by"] == "data", r
    assert "per share" in r["answer"] and "No dividend yield" in r["answer"]
    (table,) = [b for b in r["blocks"] if b.get("type") == "table"]
    assert table["columns"][0] == "Fiscal year" and table["rows"]
    y = client.post("/v1/chat", json={"message": "What is Apple's dividend yield?",
                                      "cik": "0000320193"}, headers=auth).json()  # fmt: skip
    assert y["intent"] != "dividends"
