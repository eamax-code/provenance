"""X-14: what changed in an annual report's risk factors and MD&A (docs/contracts/changes.md)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.models import Filing, FilingSection
from app.services import tenk_sections as T

CIK = "0000320193"


def _doc(risks: list[str], mdna: list[str]) -> str:
    b = 'style="font-weight:700"'
    toc = ("<p>Table of Contents</p><table><tr><td>Item 1A.</td><td>Risk Factors</td></tr>"
           "<tr><td>Item 1B.</td><td>Unresolved Staff Comments</td></tr></table>")  # fmt: skip
    body = [f"<p><span {b}>Item 1A. Risk Factors</span></p>",
            f"<p><span {b}>Risks Related to Our Business</span></p>"]  # fmt: skip
    for r in risks:
        body.append(f"<p><span {b}>{r}</span></p><p>Discussion of {r.lower()} in some depth.</p>")
    body.append(f"<p><span {b}>Item 1B. Unresolved Staff Comments</span></p><p>None.</p>")
    body.append(f"<p><span {b}>Item 7. Management's Discussion and Analysis of Financial "
                f"Condition and Results of Operations</span></p>")  # fmt: skip
    for m in mdna:
        body.append(f"<p><i>{m}</i></p><p>Text about {m}.</p>")
    body.append(f"<p><span {b}>Item 7A. Quantitative and Qualitative Disclosures</span></p>")
    return "<html><body>" + toc + "".join(body) + "</body></html>"


NOW = ["Our supply chain depends on a few suppliers in one region.",
       "Cybersecurity incidents could disrupt our services and harm customers.",
       "Artificial intelligence features may create new legal and reputational exposure.",
       "Changes in tax rates could increase our effective tax rate."]  # fmt: skip
BEFORE = ["Our supply chain depends on a few suppliers in one region.",
          "Cybersecurity incidents could disrupt our services.",
          "A pending acquisition may not close on the expected terms.",
          "Changes in tax rates could increase our effective tax rate."]  # fmt: skip


def test_section_text_skips_the_table_of_contents_and_marks_headings():
    text = T.section_text(_doc(NOW, ["Overview", "Results of Operations", "Liquidity"]), "1A")
    hs = T.headings(text)
    assert [h["heading"] for h in hs] == NOW
    assert all(h["group"] == "Risks Related to Our Business" for h in hs)
    assert hs[0]["text"].startswith("Discussion of our supply chain")
    mdna = T.headings(T.section_text(_doc(NOW, ["Overview", "Results of Operations",
                                                "Liquidity"]), "7"))  # fmt: skip
    assert [h["heading"] for h in mdna] == ["Overview", "Results of Operations", "Liquidity"]


def test_a_heading_broken_over_two_paragraphs_is_joined():
    b = 'style="font-weight:bold"'
    doc = (f"<p><span {b}>Item 1A. Risk Factors</span></p>"
           f"<p><span {b}>Our production system must ensure every airplane</span></p>"
           f"<p><span {b}>conforms to the type design, or deliveries can slow.</span></p>"
           "<p>Body text.</p>" + "".join(f"<p><span {b}>Risk number {i} heading.</span></p><p>x</p>"
                                         for i in range(3))
           + f"<p><span {b}>Item 2. Properties</span></p>")  # fmt: skip
    hs = T.headings(T.section_text(doc, "1A"))
    assert hs[0]["heading"] == ("Our production system must ensure every airplane conforms to "
                                "the type design, or deliveries can slow.")  # fmt: skip


def test_diff_classifies_unchanged_reworded_added_removed():
    now = T.headings(T.section_text(_doc(NOW, []), "1A"))
    before = T.headings(T.section_text(_doc(BEFORE, []), "1A"))
    d = T.diff(now, before)
    assert d["counts"] == {"now": 4, "before": 4, "added": 1, "removed": 1, "reworded": 1,
                           "unchanged": 2}  # fmt: skip
    assert d["added"][0]["heading"].startswith("Artificial intelligence")
    assert d["removed"][0]["heading"].startswith("A pending acquisition")
    assert (
        d["reworded"][0]["heading_before"] == "Cybersecurity incidents could disrupt our services."
    )


def _filing(db, acc, filed, period):
    f = Filing(cik=CIK, accession_number=acc, form_type="10-K", filing_date=filed,
               report_date=period, primary_document="aapl.htm",
               source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/"
               f"{acc}-index.html", first_detected_at=datetime.now(UTC),
               quality_status="ok")  # fmt: skip
    db.add(f)
    return f


def _store(db, f, risks):
    text = T.section_text(_doc(risks, ["Overview", "Results", "Liquidity"]), "1A")
    for key, t in (
        ("10k:1A", text),
        ("10k:7", T.section_text(_doc(risks, ["Overview", "Results", "Liquidity"]), "7")),
    ):
        db.add(
            FilingSection(
                cik=CIK,
                accession_number=f.accession_number,
                item=key,
                status="ok",
                text=t,
                source_url="https://www.sec.gov/Archives/x.htm",
                extractor_version=T.EXTRACTOR,
                extraction_status="ok" if len(T.headings(t)) >= 3 else "no_headings",
            )
        )


def test_changes_endpoints(client, auth, db, ingested_aapl):
    now = _filing(db, "0000320193-25-900079", date(2025, 10, 31), date(2025, 9, 27))
    before = _filing(db, "0000320193-24-900123", date(2024, 11, 1), date(2024, 9, 28))
    _store(db, now, NOW)
    db.commit()
    r = client.get(f"/v1/filings/{now.accession_number}/changes", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["reason"] == "prior_not_read"
    _store(db, before, BEFORE)
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/changes", headers=auth).json()
    assert body["filing"]["accession_number"] == now.accession_number
    assert body["prior"]["accession_number"] == before.accession_number
    assert body["risk_factors"]["counts"]["added"] == 1 and body["method"]["threshold"] == 0.6
    assert body["mdna"]["counts"]["unchanged"] == 3
    assert "fetched_at" not in str(body)
    missing = client.get("/v1/filings/0000000000-25-000001/changes", headers=auth)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "filing_not_found"
    tl = client.get(f"/v1/companies/{CIK}/timeline?types=filing&from=2024-01-01&limit=200",
                    headers=auth).json()  # fmt: skip
    flags = {i["accession_number"]: i.get("changes_available") for i in tl["data"]
             if i["form_type"] == "10-K"}  # fmt: skip
    assert flags[now.accession_number] is True and flags[before.accession_number] is False


def test_a_report_that_does_not_split_gives_no_half_diff(client, auth, db, ingested_aapl):
    now = _filing(db, "0000320193-25-900079", date(2025, 10, 31), date(2025, 9, 27))
    before = _filing(db, "0000320193-24-900123", date(2024, 11, 1), date(2024, 9, 28))
    _store(db, now, NOW)
    _store(db, before, BEFORE[:2])  # two headings: did not split
    db.commit()
    r = client.get(f"/v1/filings/{now.accession_number}/changes", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["reason"] == "not_split"


def test_table_cells_are_not_headings_and_repeats_match_by_occurrence():
    b = 'style="font-weight:700"'
    table = (f"<table><tr><td><span {b}>2026</span></td><td><span {b}>Change</span></td>"
             f"<td><span {b}>2025</span></td></tr></table>")  # fmt: skip
    layout = f"<table><tr><td><span {b}>Segment Operating Performance</span></td></tr></table>"
    doc = (f"<p><span {b}>Item 7. Management's Discussion and Analysis of Financial Condition"
           f"</span></p>{layout}<p>text</p>{table}<p><span {b}>Revenue</span></p><p>a</p>"
           f"<p><span {b}>Revenue</span></p><p>b</p><p><span {b}>Liquidity</span></p><p>c</p>"
           f"<p><span {b}>Item 7A. Market Risk</span></p>")  # fmt: skip
    hs = T.headings(T.section_text(doc, "7"))
    assert [h["heading"] for h in hs] == ["Segment Operating Performance", "Revenue", "Revenue",
                                          "Liquidity"]  # fmt: skip
    d = T.diff(hs, hs[:2] + hs[3:])  # one "Revenue" fewer last year
    assert d["counts"]["unchanged"] == 3 and d["counts"]["added"] == 1
