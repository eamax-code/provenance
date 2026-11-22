"""E-4: segments from the Notes data sets, on real rows of Apple's, Microsoft's and JPMorgan's
latest 10-Ks (tests/fixtures/segments, cut from the SEC data sets)."""

from __future__ import annotations

from datetime import date
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
                        "Corporate and other", "Consolidated"}  # fmt: skip
    assert biz["Corporate and other"][0] == "reconciling"
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
    assert pre["Reconciling items"][0] == "reconciling"
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
    assert top["label_source"] == "member_name"
    assert biz["reconciling"][0]["label"].startswith("Corporate")
    r = client.get("/v1/companies/320193/segments", headers=auth)
    assert r.status_code == 200 and r.json()["kinds"][0]["kind"] == "business"
    assert client.get("/v1/companies/789019/segments", headers=auth).status_code in (404,)
    o = client.get("/v1/public/companies/320193/overview").json()
    assert o["segments"]["filing"]["accession_number"] == b["filing"]["accession_number"]
    from app.api.routes_mcp import TOOLS

    assert TOOLS["company_segments"]["path"] == "/v1/companies/{cik}/segments"


def test_a_segments_own_eliminations_are_keyed_apart():
    c = segments.classify({"BusinessSegments": "EuropeSteelGroup",
                           "ConsolidationItems": "IntersegmentElimination"})  # fmt: skip
    key = "BusinessSegments=EuropeSteelGroup;ConsolidationItems=IntersegmentElimination"
    assert c == ("business", "reconciling", key)
    assert segments.member_label(c[2]) == "Europe Steel Group: intersegment eliminations"
    assert segments.member_label("BusinessSegments=AmericasSegment") == "Americas"
    assert segments.member_label("ConsolidationItems=CorporateNonSegment").startswith("Corporate")


def test_no_share_of_revenue_when_the_latest_year_is_unreconciled(db, ingested_aapl):
    from app.db.models import CompanySegment

    segments.load(db, FIX / "aapl.zip")
    for r in db.query(CompanySegment).filter(CompanySegment.kind == "product"):
        r.status = "unreconciled"
    db.commit()
    kinds = {k["kind"]: k for k in segments.for_company(db, "0000320193")["kinds"]}
    assert all(s["share_of_revenue_pct"] is None for s in kinds["product"]["segments"])
    assert kinds["business"]["segments"][0]["share_of_revenue_pct"] == 42.9  # ok stays


def test_a_single_unreconciled_member_is_hidden_with_its_reason(db, client, auth, ingested_aapl):
    """XOM showed one product line, "Sales and other operating revenue", unreconciled, in place
    of its four segments: a kind like that is hidden, and an empty block says why."""
    from app.db.models import CompanySegment

    segments.load(db, FIX / "aapl.zip")
    q = db.query(CompanySegment).filter(CompanySegment.kind == "product")
    keep = "ProductOrService=IPhone"
    assert q.filter(CompanySegment.member == keep).count()
    q.filter(CompanySegment.role == "segment", CompanySegment.member != keep).delete()
    q.filter(CompanySegment.kind == "product").update({"status": "unreconciled"})
    db.commit()
    b = segments.for_company(db, "0000320193")
    assert {k["kind"] for k in b["kinds"]} == {"business", "geographic"}
    assert b["hidden"] == [{"kind": "product", "reason": "single unreconciled member",
                            "member": "IPhone"}]  # fmt: skip
    assert b["hidden_reason"] is None  # other kinds still show
    # one member that adds up is kept: a single-segment company is a real answer
    q.filter(CompanySegment.kind == "product").update({"status": "ok"})
    db.commit()
    assert "product" in {k["kind"] for k in segments.for_company(db, "0000320193")["kinds"]}
    # nothing left: the block is empty and explains itself
    db.query(CompanySegment).filter(CompanySegment.kind != "product").delete()
    q.filter(CompanySegment.kind == "product").update({"status": "unreconciled"})
    db.commit()
    r = client.get("/v1/companies/320193/segments", headers=auth).json()
    assert r["kinds"] == [] and r["hidden_reason"] == "single unreconciled member"
    o = client.get("/v1/public/companies/320193/overview").json()["segments"]
    assert o["kinds"] == [] and o["hidden_reason"] == "single unreconciled member"


LAB = """<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
  xmlns:xlink="http://www.w3.org/1999/xlink">
 <link:labelLink xlink:type="extended">
  <link:loc xlink:type="locator" xlink:href="aapl.xsd#aapl_IPhoneMember" xlink:label="loc1"/>
  <link:labelArc xlink:type="arc" xlink:from="loc1" xlink:to="lab1"/>
  <link:label xlink:type="resource" xlink:label="lab1"
    xlink:role="http://www.xbrl.org/2003/role/terseLabel">iPhone</link:label>
  <link:label xlink:type="resource" xlink:label="lab1"
    xlink:role="http://www.xbrl.org/2003/role/label">iPhone [Member]</link:label>
  <link:loc xlink:type="locator" xlink:href="aapl.xsd#aapl_RestOfAsiaPacificSegmentMember"
    xlink:label="loc2"/>
  <link:labelArc xlink:type="arc" xlink:from="loc2" xlink:to="lab2"/>
  <link:label xlink:type="resource" xlink:label="lab2"
    xlink:role="http://www.xbrl.org/2003/role/label">Rest of Asia Pacific [Member]</link:label>
  <link:loc xlink:type="locator" xlink:href="aapl.xsd#aapl_NetSales" xlink:label="loc3"/>
  <link:labelArc xlink:type="arc" xlink:from="loc3" xlink:to="lab3"/>
  <link:label xlink:type="resource" xlink:label="lab3"
    xlink:role="http://www.xbrl.org/2003/role/label">Net sales</link:label>
 </link:labelLink>
</link:linkbase>"""


def test_labels_come_from_the_filings_own_linkbase():
    from app.services import segment_labels

    labels = segment_labels.parse_labels(LAB)
    assert labels == {"IPhone": "iPhone", "RestOfAsiaPacificSegment": "Rest of Asia Pacific"}
    idx = '<a href="/Archives/edgar/data/1/000000000126000001/x-20260630.xsd">x</a>'
    assert segment_labels.lab_url(idx).endswith(".xsd")  # linkbase embedded in the schema
    idx += '<a href="/Archives/edgar/data/1/000000000126000001/x-20260630_lab.xml">l</a>'
    assert segment_labels.lab_url(idx).endswith("_lab.xml")


def _lab(*members):
    """A label linkbase: (concept, role, text) per label."""
    out = ['<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" '
           'xmlns:xlink="http://www.w3.org/1999/xlink"><link:labelLink>']  # fmt: skip
    for i, (concept, role, text) in enumerate(members):
        out.append(f'<link:loc xlink:href="x.xsd#{concept}" xlink:label="l{i}"/>'
                   f'<link:labelArc xlink:from="l{i}" xlink:to="r{i}"/>'
                   f'<link:label xlink:label="r{i}" xlink:role="http://www.xbrl.org/2003/role/'
                   f'{role}">{text}</link:label>')  # fmt: skip
    return "".join(out) + "</link:labelLink></link:linkbase>"


def test_member_suffix_is_stripped_from_any_role_and_taxonomy_wording_gets_plain_names(
    db, ingested_aapl
):
    """Berkshire's labels came through as "McLane [Member]"; JPM's reconciling row read
    "Segment Reporting, Reconciling Item, Excluding Corporate Nonsegment"."""
    from types import SimpleNamespace

    from app.db.models import CompanySegment
    from app.services import segment_labels

    labels = segment_labels.parse_labels(_lab(
        ("brka_McLaneMember", "terseLabel", "McLane [Member]"),
        ("brka_BNSFMember", "label", "BNSF [Member]"),
        ("brka_InsuranceDomain", "label", "Insurance [Domain]")))  # fmt: skip
    assert labels == {"McLane": "McLane", "BNSF": "BNSF"}  # Domain is not a Member concept
    assert segment_labels.clean("Insurance [Domain]") == "Insurance"

    segments.load(db, FIX / "aapl.zip")
    acc = db.query(CompanySegment.accession_number).first()[0]
    db.add_all(
        [
            CompanySegment(**{**base, "member": m, "label": "x", "role": "reconciling"})
            for base in [
                dict(
                    accession_number=acc,
                    cik="0000320193",
                    kind="business",
                    metric="revenue",
                    period_end=date(2025, 9, 27),
                    form_type="10-K",
                    fiscal_year=2025,
                    filed_date=date(2025, 10, 31),
                    tag="Revenues",
                    unit="USD",
                    status="ok",
                    source="t",
                    value=1,
                )
            ]
            for m in (
                "ConsolidationItems=MaterialReconcilingItems",
                "BusinessSegments=IPhone;ConsolidationItems=IntersegmentElimination",
            )
        ]
    )
    db.commit()
    lab = _lab(
        ("us-gaap_MaterialReconcilingItemsMember", "label",
         "Segment Reporting, Reconciling Item, Excluding Corporate Nonsegment [Member]"),
        ("us-gaap_IntersegmentEliminationMember", "label",
         "Segment Reporting, Reconciling Item, Intersegment Elimination [Member]"),
        ("aapl_IPhoneMember", "terseLabel", "iPhone"),
        ("aapl_AmericasSegmentMember", "label", "Americas [Member]"))  # fmt: skip
    pages = {"index": '<a href="/Archives/edgar/data/320193/x/aapl_lab.xml">l</a>', "lab": lab}
    sec = SimpleNamespace(get_text=lambda url: SimpleNamespace(
        data=pages["lab"] if url.endswith("_lab.xml") else pages["index"]))  # fmt: skip
    assert segment_labels.apply_filing(db, sec, "0000320193", acc) > 0
    got = dict(db.query(CompanySegment.member, CompanySegment.label)
               .filter(CompanySegment.accession_number == acc).distinct())  # fmt: skip
    assert got["ConsolidationItems=MaterialReconcilingItems"] == "Reconciling items"
    own = "BusinessSegments=IPhone;ConsolidationItems=IntersegmentElimination"
    assert got[own] == "iPhone: intersegment eliminations"
    assert got["BusinessSegments=AmericasSegment"] == "Americas"
    assert not any("[Member]" in v for v in got.values())
    src = dict(db.query(CompanySegment.member, CompanySegment.label_source)
               .filter(CompanySegment.accession_number == acc).distinct())  # fmt: skip
    assert src["ConsolidationItems=MaterialReconcilingItems"] == "member_name"
    assert src["BusinessSegments=AmericasSegment"] == "filing_label"
