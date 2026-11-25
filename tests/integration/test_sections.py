"""Q-09: a 10-K item's text as filed (docs/contracts/sections.md)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.db.models import FilingSection
from app.services import tenk_sections as T
from tests.integration.test_changes import CIK, NOW, _doc, _filing

ACC = "0000320193-26-900100"


def _read(doc: str) -> str:
    return "\n\n".join(t for t, _ in T.paragraphs(doc))


def test_located_is_an_exact_slice_past_the_table_of_contents():
    doc = _doc(NOW, ["Overview", "Results", "Liquidity"])
    loc = T.located(doc, "1A")
    text = _read(doc)
    assert text[loc["start"] : loc["end"]] == loc["text"]
    assert loc["heading"] == "Item 1A. Risk Factors"
    assert loc["text"].startswith("Risks Related to Our Business")  # not the contents entry
    assert text[loc["end"] :].startswith("\n\nItem 1B. Unresolved Staff Comments")
    first = loc["subheadings"][1]
    assert text[first[0] : first[1]] == NOW[0] and first[2] is False
    assert loc["subheadings"][0][2] is True  # "Risks Related to Our Business", a group
    assert "#" not in loc["text"]


def _seed(db):
    from datetime import UTC, datetime

    from app.db.models import Company

    db.add(Company(cik=CIK, legal_name="Apple Inc.", ticker="AAPL", source_url="https://www.sec.gov/",
                   first_detected_at=datetime.now(UTC), quality_status="ok"))  # fmt: skip
    f = _filing(db, ACC, date(2026, 10, 31), date(2026, 9, 26))
    doc = _doc(NOW, ["Overview", "Results", "Liquidity"])
    filed, layout = T.layout_of(doc, "1A", "aapl.htm")
    db.add(FilingSection(cik=CIK, accession_number=ACC, item="10k:1A", status="ok",
                         text=T.section_text(doc, "1A"), filed_text=filed, layout=layout,
                         source_url="https://www.sec.gov/Archives/edgar/data/320193/"
                         "000032019326900100/aapl.htm", extractor_version=T.EXTRACTOR,
                         extraction_status="ok"))  # fmt: skip
    db.commit()
    return f, doc


def test_item_as_filed_with_offsets_and_coverage(client, auth, db):
    _, doc = _seed(db)
    listed = client.get(f"/v1/filings/{ACC}/sections", headers=auth).json()
    assert [i["item"] for i in listed["items"]] == ["1A"]
    assert "other items are not read yet" in listed["coverage"]
    body = client.get(f"/v1/filings/{ACC}/sections/1A", headers=auth).json()
    assert body["heading"] == "Item 1A. Risk Factors" and body["title"] == "Risk Factors"
    assert "##" not in body["text"] and "\n# " not in body["text"]
    o = body["offsets"]
    assert _read(doc)[o["start"] : o["end"]] == body["text"]
    sub = body["subheadings"][1]
    assert set(sub) == {"group", "start", "end"}  # offsets only
    assert _read(doc)[sub["start"] : sub["end"]] == NOW[0]
    doc_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019326900100/aapl.htm"
    assert body["document"] == {"url": doc_url, "name": "aapl.htm"}
    assert body["filing_url"].startswith("https://www.sec.gov/Archives/")
    missing = client.get(f"/v1/filings/{ACC}/sections/7", headers=auth)
    assert missing.status_code == 404
    err = missing.json()["error"]
    assert err["code"] == "section_not_held" and "other items are not read yet" in err["message"]
    assert client.get(f"/v1/filings/{ACC}/sections/2", headers=auth).status_code == 422
    assert client.get("/v1/filings/0000320193-26-999999/sections",
                      headers=auth).status_code == 404  # fmt: skip
    assert json.dumps(body).count("first_detected_at") == 0


def test_mcp_filing_section_quotes_as_filed(client, auth, db):
    _seed(db)

    def call(args):
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "filing_section", "arguments": args}}  # fmt: skip
        return client.post("/mcp", json=rpc, headers=auth).json()["result"]

    ok = call({"accession": ACC, "item": "1A"})
    assert ok["isError"] is False
    body = json.loads(ok["content"][0]["text"])
    assert body["heading"] == "Item 1A. Risk Factors" and body["text"].startswith("Risks Related")
    held = call({"accession": ACC, "item": "7"})
    assert held["isError"] is True and "section_not_held" in held["content"][0]["text"]


def test_the_reader_page_route_takes_only_an_accession_and_1a_or_7(client):
    """Q-09: /filings/{accession}/{1A|7}/ is the reader page; anything else under /filings/
    (the page's own script and stylesheet) falls through to the static mount."""
    pages = [r for r in client.app.routes
             if getattr(r, "path", "").startswith("/filings/{accession")]  # fmt: skip
    assert len(pages) == 2
    for r in pages:
        for path in ("/filings/section.js", "/filings/section.css", "/filings/0000320193-26-000026",
                     "/filings/0000320193-26-000026/2", "/filings/320193-26-26/1A"):  # fmt: skip
            assert r.path_regex.match(path) is None, (r.path, path)
    acc = "0000320193-26-000026"
    urls = (f"/filings/{acc}/1A", f"/filings/{acc}/7/")
    hits = [r.path_regex.match(p) for r in pages for p in urls]
    assert {(m.group("accession"), m.group("item")) for m in hits if m} == {(acc, "1A"), (acc, "7")}
    # the routes serve ui's reader page, and its own files still come from the static mount
    page = (Path(__file__).parents[2] / "site" / "filings" / "section.html").read_text("utf-8")
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200 and r.text == page, url
    assert '<script src="/filings/section.js"' in page
    assert client.get("/filings/section.js").status_code == 200
    assert client.get("/filings/section.css").status_code == 200
    assert client.get(f"/filings/{acc}/2/").status_code == 404


def test_a_search_hit_on_item_1a_opens_the_reader_at_the_hit(client, auth, db):
    """Q-09: a filing-search hit on Items 1A and 7 carries section_offset; the section's text as
    filed, from that offset, is the hit."""
    from app.services import filing_search

    _seed(db)
    filing_search.reset_section_map()
    r = client.get("/v1/search/filings", params={"q": "cybersecurity incidents", "cik": CIK},
                   headers=auth)  # fmt: skip
    assert r.status_code == 200, r.text
    (hit,) = [h for h in r.json()["hits"] if h["section"]["item"] == "10k:1A"]
    body = client.get(f"/v1/filings/{ACC}/sections/1A", headers=auth).json()
    at = hit["section_offset"]
    assert at is not None and body["text"][at:].lower().startswith("cybersecurity incidents")
