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


def test_no_share_of_revenue_when_segments_include_sales_between_them(db, ingested_aapl):
    """XOM's segment revenue includes intersegment sales, eliminated below the segments: shares
    of consolidated revenue would add up to 136%."""
    from app.db.models import CompanySegment

    segments.load(db, FIX / "aapl.zip")
    biz = db.query(CompanySegment).filter(CompanySegment.kind == "business",
                                          CompanySegment.role == "segment")  # fmt: skip
    for r in biz:
        r.value = r.value * 2  # gross of intersegment sales; still ok through reconciling items
    db.commit()
    kinds = {k["kind"]: k for k in segments.for_company(db, "0000320193")["kinds"]}
    assert all(s["share_of_revenue_pct"] is None for s in kinds["business"]["segments"])
    assert kinds["product"]["segments"][0]["share_of_revenue_pct"] is not None  # adds up alone


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


def test_two_axis_segments_are_summed_only_when_safe_and_they_add_up():
    """E-4c: XOM tags each segment by US and non-US. Summing over geography gives the segments,
    but only when no geography member holds others and the sums make the consolidated figure."""
    assert segments.classify2({"BusinessSegments": "Upstream", "Geographical": "US"}) == [
        ("business", "BusinessSegments=Upstream", "Geographical", "US"),
        ("geographic", "Geographical=US", "BusinessSegments", "Upstream"),
    ]
    assert segments.classify2({"BusinessSegments": "Upstream", "LegalEntity": "Sub"}) == []
    assert segments.classify2({"BusinessSegments": "A", "Geographical": "US",
                               "ConsolidationItems": "IntersegmentElimination"}) == []  # fmt: skip
    D = Decimal
    cells = {"Geographical": {
        "BusinessSegments=Upstream": {"US": D(51489), "NonUs": D(55662)},
        "BusinessSegments=EnergyProducts": {"US": D(118497), "NonUs": D(173119)},
        "BusinessSegments=ChemicalProducts": {"US": D(14509), "NonUs": D(18473)},
        "BusinessSegments=SpecialtyProducts": {"US": D(7655), "NonUs": D(12805)}}}  # fmt: skip
    recon = {"ConsolidationItems=CorporateNonSegment": D(1034),
             "ConsolidationItems=IntersegmentElimination": D(-121005)}  # fmt: skip
    summed = segments.summed_over(cells, D(332238), recon)
    assert summed == {"BusinessSegments=Upstream": D(107151),
                      "BusinessSegments=EnergyProducts": D(291616),
                      "BusinessSegments=ChemicalProducts": D(32982),
                      "BusinessSegments=SpecialtyProducts": D(20460)}  # fmt: skip
    assert segments.summed_over(cells, D(500000), recon) is None  # does not add up: none
    # a geography member that holds others (NonUs = Canada + Europe) would count twice
    nested = {"Geographical": {
        "BusinessSegments=A": {"US": D(50), "NonUs": D(50), "CA": D(20), "EU": D(30)},
        "BusinessSegments=B": {"US": D(25), "NonUs": D(25), "CA": D(10), "EU": D(15)}}}  # fmt: skip
    assert segments.summed_over(nested, D(150), {}) is None
    assert segments.summed_over(nested, D(225), {}) is None


def test_two_axis_sums_one_axis_precedence_tag_choice_and_plain_totals(tmp_path):
    """Through the data set reader: XOM's segments come from the summed two-axis facts; the
    product kind takes the tag whose lines add up; a member's own total beats its
    operating-segments part."""
    import zipfile

    adsh = "0000034088-26-000045"
    sub = ("adsh\tcik\tname\tform\tperiod\tfy\tfp\tfiled\n"
           f"{adsh}\t34088\tEXXON MOBIL CORP\t10-K\t20251231\t2025\tFY\t20260218\n")  # fmt: skip
    hashes = {}

    def dimh(segs):
        return hashes.setdefault(segs, f"0x{len(hashes) + 1:032x}") if segs else "0x00"

    facts = [
        ("Revenues", "", 332238),
        ("Revenues", "BusinessSegments=Upstream;Geographical=US;", 51489),
        ("Revenues", "BusinessSegments=Upstream;Geographical=NonUs;", 55662),
        ("Revenues", "BusinessSegments=EnergyProducts;Geographical=US;", 118497),
        ("Revenues", "BusinessSegments=EnergyProducts;Geographical=NonUs;", 173119),
        ("Revenues", "BusinessSegments=ChemicalProducts;Geographical=US;", 14509),
        ("Revenues", "BusinessSegments=ChemicalProducts;Geographical=NonUs;", 18473),
        ("Revenues", "BusinessSegments=SpecialtyProducts;Geographical=US;", 7655),
        ("Revenues", "BusinessSegments=SpecialtyProducts;Geographical=NonUs;", 12805),
        ("Revenues", "ConsolidationItems=CorporateNonSegment;", 1034),
        ("Revenues", "ConsolidationItems=IntersegmentElimination;", -121005),
        # operating-segments part first in the file, the member's own total after it
        ("Revenues", "ConsolidationItems=OperatingSegments;"
                     "ProductOrService=SalesAndOtherOperatingRevenue;", 323820),
        ("Revenues", "ProductOrService=SalesAndOtherOperatingRevenue;", 323905),
        ("Revenues", "ProductOrService=IncomeFromEquityAffiliates;", 5064),
        ("Revenues", "ProductOrService=OtherRevenue;", 3269),
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "", 226909),
        ("RevenueFromContractWithCustomerExcludingAssessedTax",
         "ProductOrService=SalesAndOtherOperatingRevenue;", 226909),
    ]  # fmt: skip
    num = ["adsh\ttag\tversion\tddate\tqtrs\tuom\tdimh\tiprx\tvalue\tfootnote\tfootlen\tdimn"
           "\tcoreg\tdurp\tdatp\tdcml"]  # fmt: skip
    for tag, segs, v in facts:
        n = str(segs.count("="))
        num.append("\t".join((adsh, tag, "us-gaap/2025", "20251231", "4", "USD", dimh(segs),
                              "0", f"{v * 1000000}", "", "0", n, "", "0", "0", "-6")))  # fmt: skip
    dim = ["dimhash\tsegments\tsegt"] + [f"{h}\t{s}\t0" for s, h in hashes.items()]
    path = tmp_path / "2026_02_notes.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sub.tsv", sub)
        z.writestr("num.tsv", "\n".join(num) + "\n")
        z.writestr("dim.tsv", "\n".join(dim) + "\n")
    rows = segments.parse_notes_zip(path)
    biz = _latest(rows, "business", "revenue")
    assert biz["Upstream"] == ("segment", 107151.0, "ok")
    assert biz["Energy Products"] == ("segment", 291616.0, "ok")
    assert biz["Intersegment eliminations"][0] == "reconciling"
    prod = _latest(rows, "product", "revenue")
    assert prod["Sales And Other Operating Revenue"] == ("segment", 323905.0, "ok")
    assert {r["tag"] for r in rows if r["kind"] == "product"} == {"Revenues"}
    assert len([k for k, v in prod.items() if v[0] == "segment"]) == 3


def test_one_axis_members_and_summed_two_axis_members_combine_and_totals_give_way():
    """Chevron tags All Other alone, Upstream and Downstream by US and non-US, and the total of
    its reportable segments under a US-GAAP member: kept as "Reportable segments (combined)"
    only where nothing finer adds up."""
    D = Decimal
    total = "ReportableSegmentAggregationBeforeOtherOperatingSegment"
    key = f"BusinessSegments={total}"
    assert segments.classify({"BusinessSegments": total,
                              "ConsolidationItems": "OperatingSegments"})[2] == key  # fmt: skip
    assert segments.member_label(key) == "Reportable segments (combined)"
    assert segments.classify2({"BusinessSegments": total, "Geographical": "US"}) == []
    cells = {"Geographical": {
        "BusinessSegments=DownstreamSegment": {"US": D(65913), "NonUs": D(65924)},
        "BusinessSegments=UpstreamSegment": {"US": D(20005), "NonUs": D(36545)},
        "BusinessSegments=AllOtherSegments": {"US": D(1), "NonUs": D(1)}}}  # fmt: skip
    base = {"BusinessSegments=AllOtherSegments": D(644)}
    got = segments.summed_over(cells, D(189031), {}, base)
    assert got == {"BusinessSegments=AllOtherSegments": D(644),  # the one-axis figure wins
                   "BusinessSegments=DownstreamSegment": D(131837),
                   "BusinessSegments=UpstreamSegment": D(56550)}  # fmt: skip
    assert segments.summed_over(cells, D(250000), {}, base) is None


def test_the_all_segments_total_never_sits_beside_real_segments(tmp_path):
    """Caterpillar tagged its reportable segments' total beside the segments, which counted them
    twice; an intersegment line is a reconciling item, not a product."""
    import zipfile

    assert segments.classify({"ProductOrService": "Intersegment"})[1] == "reconciling"
    assert segments.is_total("BusinessSegments=ReportableSegmentsAggregation")  # Watts' own name
    assert not segments.is_total("BusinessSegments=ReportableSegmentsEurope")
    adsh = "0000018230-26-000010"
    sub = ("adsh\tcik\tname\tform\tperiod\tfy\tfp\tfiled\n"
           f"{adsh}\t18230\tCATERPILLAR INC\t10-K\t20251231\t2025\tFY\t20260215\n")  # fmt: skip
    total = "ReportableSegmentAggregationBeforeOtherOperatingSegment"
    facts = [("", 67589), (f"BusinessSegments={total};", 68897),
             ("BusinessSegments=PowerEnergy;", 27143), ("BusinessSegments=Construction;", 25060),
             ("BusinessSegments=Resource;", 12474), ("BusinessSegments=Financial;", 4220),
             ("ConsolidationItems=IntersegmentElimination;", -1308)]  # fmt: skip
    hashes = {s: f"0x{i:032x}" for i, (s, _) in enumerate(facts, 1) if s}
    num = ["adsh\ttag\tversion\tddate\tqtrs\tuom\tdimh\tiprx\tvalue\tfootnote\tfootlen\tdimn"
           "\tcoreg\tdurp\tdatp\tdcml"]  # fmt: skip
    for segs, v in facts:
        num.append("\t".join((adsh, "Revenues", "us-gaap/2025", "20251231", "4", "USD",
                              hashes.get(segs, "0x00"), "0", f"{v * 1000000}", "", "0",
                              str(segs.count("=")), "", "0", "0", "-6")))  # fmt: skip
    path = tmp_path / "2026_02_notes.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sub.tsv", sub)
        z.writestr("num.tsv", "\n".join(num) + "\n")
        z.writestr("dim.tsv", "dimhash\tsegments\tsegt\n"
                   + "\n".join(f"{h}\t{s}\t0" for s, h in hashes.items()) + "\n")  # fmt: skip
    biz = _latest(segments.parse_notes_zip(path), "business", "revenue")
    assert "Reportable segments (combined)" not in biz
    assert {k for k, v in biz.items() if v[0] == "segment"} == {
        "Power Energy",
        "Construction",
        "Resource",
        "Financial",
    }
