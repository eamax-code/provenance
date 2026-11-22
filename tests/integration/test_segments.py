"""E-4: segments from the Notes data sets, on real rows of Apple's, Microsoft's and JPMorgan's
latest 10-Ks (tests/fixtures/segments, cut from the SEC data sets)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.services import segments

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "segments"


def _latest(rows, kind, metric):
    end = max(r["period_end"] for r in rows if r["kind"] == kind and r["metric"] == metric)
    return {r["label"]: (r["role"], float(r["value"]) / 1e6, r["status"]) for r in rows
            if r["kind"] == kind and r["metric"] == metric and r["period_end"] == end}  # fmt: skip


def test_apple_business_geographic_and_product():
    rows = segments.parse_notes_zip(FIX / "aapl.zip")
    biz = _latest(rows, "business", "operating_income")
    assert set(biz) == {"Americas", "Europe", "Greater China", "Japan", "Rest Of Asia Pacific",
                        "Corporate and other (not a segment)", "Consolidated"}  # fmt: skip
    assert biz["Corporate and other (not a segment)"][0] == "reconciling"
    assert biz["Consolidated"] == ("consolidated", 133050.0, "ok")
    geo = _latest(rows, "geographic", "revenue")
    assert set(geo) == {"United States", "China", "Other Countries", "Consolidated"}
    assert sum(v for k, (r, v, s) in geo.items() if r == "segment") == geo["Consolidated"][1]
    prod = _latest(rows, "product", "revenue")
    assert "Product" not in prod  # the subtotal of iPhone, Mac, iPad and Wearables is dropped
    assert {"IPhone", "Mac", "IPad", "Service"} <= set(prod) and prod["IPhone"][2] == "ok"


def test_microsoft_three_segments_add_up():
    rows = segments.parse_notes_zip(FIX / "msft.zip")
    rev = _latest(rows, "business", "revenue")
    names = {k for k, (r, _, _) in rev.items() if r == "segment"}
    assert names == {"Intelligent Cloud", "Productivity And Business Processes",
                     "More Personal Computing"}  # fmt: skip
    total = sum(v for k, (r, v, s) in rev.items() if r == "segment")
    assert total == rev["Consolidated"][1] == 331839.0 and rev["Intelligent Cloud"][2] == "ok"


def test_bank_reports_pretax_income_by_segment_with_reconciling_items():
    rows = segments.parse_notes_zip(FIX / "jpm.zip")
    pre = _latest(rows, "business", "pretax_income")
    assert pre["Commercial And Investment Bank"][0] == "segment"
    assert pre["Material reconciling items"][0] == "reconciling"
    assert pre["Consolidated"] == ("consolidated", 72595.0, "ok")
    assert any(r["tag"] == "RevenuesNetOfInterestExpense" for r in rows if r["metric"] == "revenue")


def test_unreconciled_when_segments_do_not_add_up():
    members = {"A": Decimal(60), "B": Decimal(30)}
    assert segments.drop_subtotals(members, Decimal(100)) == members  # nothing to drop
    assert segments.subtotals({"P": Decimal(90), "X": Decimal(60), "Y": Decimal(30),
                               "Z": Decimal(10)}) == {"P"}  # fmt: skip
    assert segments.classify({"BusinessSegments": "Cloud",
                              "ConsolidationItems": "OperatingSegments"}) == (
        "business", "segment", "BusinessSegments=Cloud")  # fmt: skip
    assert segments.classify({"DebtInstrument": "Notes2030"}) is None


def test_overview_block_endpoint_and_mcp(db, client, auth, ingested_aapl):
    segments.load(db, FIX / "aapl.zip")
    b = segments.for_company(db, "0000320193")
    assert b["filing"]["form_type"] == "10-K" and b["filing"]["source_url"].endswith("index.html")
    kinds = {k["kind"]: k for k in b["kinds"]}
    assert set(kinds) == {"business", "geographic", "product"}
    biz = kinds["business"]
    latest = biz["periods"][0]
    assert len(biz["periods"]) == 3 and biz["metrics"]["revenue"]["status"][latest] == "ok"
    top = biz["segments"][0]
    assert top["label"] == "Americas" and top["share_of_revenue_pct"] == 42.9
    assert top["key"] == "BusinessSegments=AmericasSegment"
    assert biz["reconciling"][0]["label"].startswith("Corporate")
    r = client.get("/v1/companies/320193/segments", headers=auth)
    assert r.status_code == 200 and r.json()["kinds"][0]["kind"] == "business"
    assert client.get("/v1/companies/789019/segments", headers=auth).status_code in (404,)
    o = client.get("/v1/public/companies/320193/overview").json()
    assert o["segments"]["filing"]["accession_number"] == b["filing"]["accession_number"]
    from app.api.routes_mcp import TOOLS

    assert TOOLS["company_segments"]["path"] == "/v1/companies/{cik}/segments"
