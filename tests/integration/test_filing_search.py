"""Q-01: full-text search inside filings (docs/contracts/filing-search.md)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.db.models import Company, Filing, FilingSection
from app.services import filing_search as fs

DEMO = {"X-API-Key": "demo"}
A = "https://www.sec.gov/Archives/edgar/data/"

SECTIONS = [
    # cik, accession, form, filed, item, text
    ("0002999001", "0002999001-26-000002", "S-1", date(2026, 10, 20), "pr:risk",
     "There is substantial doubt about our ability to continue as a going concern. Tariffs on "
     "imported parts could raise our costs."),
    ("0002999001", "0002999001-26-000005", "S-1/A", date(2026, 11, 2), "pr:risk",
     "Our auditors noted going concerns in prior years; supply chain disruptions continue."),
    ("0002999002", "0002999002-26-000010", "10-K", date(2026, 3, 1), "10k:1A",
     "Supply chain disruption, including tariffs and duties on goods from China, may hurt "
     "margins. We identified a material weakness in internal control."),
    ("0002999002", "0002999002-25-000010", "10-K", date(2025, 3, 1), "10k:7",
     "Revenue grew as duties fell. Management's discussion of results."),
    ("0002999003", "0002999003-26-000001", "8-K", date(2026, 8, 1), "ex:99.1",
     "Record revenue. Tariff refunds lifted gross margin; supply-chain costs were flat."),
]  # fmt: skip


@pytest.fixture
def stored(db):
    now = datetime.now(UTC)
    names = {"0002999001": ("Lumen Example Labs, Inc.", "LMNX"),
             "0002999002": ("Harbor Freight Example Corp", None),
             "0002999003": ("Corvid Example Inc.", "CRVD")}  # fmt: skip
    for cik, (name, ticker) in names.items():
        db.add(Company(cik=cik, legal_name=name, ticker=ticker, source_url=A,
                       first_detected_at=now, last_processed_at=now))  # fmt: skip
    for cik, acc, form, filed, item, text in SECTIONS:
        url = f"{A}{int(cik)}/{acc.replace('-', '')}/doc.htm"
        db.add(Filing(cik=cik, accession_number=acc, form_type=form, filing_date=filed,
                      source_url=url, first_detected_at=now, quality_status="ok"))  # fmt: skip
        db.add(FilingSection(cik=cik, accession_number=acc, item=item, status="ok", text=text,
                             source_url=url))  # fmt: skip
    db.commit()


def _get(client, auth, **params):
    return client.get("/v1/search/filings", params=params, headers=auth)


def _accs(body):
    return [h["filing"]["accession_number"] for h in body["hits"]]


def test_phrase_is_matched_exactly_and_words_by_stem(client, auth, db, stored):
    body = _get(client, auth, q='"going concern"').json()
    # "going concerns" (the S-1/A) is not the phrase as written
    assert _accs(body) == ["0002999001-26-000002"]
    assert body["query"]["phrases"] == ["going concern"] and body["query"]["words"] == []
    # unquoted, words match by stem: "tariffs" finds "Tariff" and "tariffs"
    accs = _accs(_get(client, auth, q="tariffs").json())
    assert set(accs) == {"0002999001-26-000002", "0002999002-26-000010", "0002999003-26-000001"}
    # punctuation between the words of a phrase is ignored: "supply-chain" holds "supply chain"
    accs = _accs(_get(client, auth, q='"supply chain"').json())
    assert set(accs) == {"0002999001-26-000005", "0002999002-26-000010", "0002999003-26-000001"}


def test_or_and_exclusion(client, auth, db, stored):
    accs = _accs(_get(client, auth, q="tariff or duties -china").json())
    assert set(accs) == {"0002999001-26-000002", "0002999002-25-000010", "0002999003-26-000001"}
    body = _get(client, auth, q='"supply chain" -"going concerns"').json()
    assert "0002999001-26-000005" not in _accs(body)
    assert body["query"]["excluded"] == ["going concerns"]


def test_filters_sort_and_pages(client, auth, db, stored):
    # newest filing first; a form includes its amendments
    assert _accs(_get(client, auth, q="supply", form="S-1").json()) == ["0002999001-26-000005"]
    assert _accs(_get(client, auth, q="revenue", section="annual_report").json()) == [
        "0002999002-25-000010"]  # fmt: skip
    assert _accs(_get(client, auth, q="revenue", section="ex:99.1").json()) == [
        "0002999003-26-000001"]  # fmt: skip
    assert _accs(_get(client, auth, q="tariffs", filed_to="2026-07-31").json()) == [
        "0002999002-26-000010"]  # fmt: skip
    assert _accs(_get(client, auth, q="tariffs", filed_from="2026-08-01").json()) == [
        "0002999001-26-000002", "0002999003-26-000001"]  # fmt: skip
    assert _accs(_get(client, auth, q="tariffs", cik="2999002").json()) == ["0002999002-26-000010"]
    first = _get(client, auth, q="tariffs", limit=2).json()
    assert _accs(first) == ["0002999001-26-000002", "0002999003-26-000001"]
    assert first["meta"] == {"limit": 2, "offset": 0, "has_more": True, "next_offset": 2}
    second = _get(client, auth, q="tariffs", limit=2, offset=2).json()
    assert _accs(second) == ["0002999002-26-000010"] and second["meta"]["has_more"] is False
    ranked = _get(client, auth, q="tariffs", sort="relevance").json()
    assert all(0 < h["relevance"] <= 1 for h in ranked["hits"])
    assert all(h["relevance"] is None for h in first["hits"])


def test_hit_shape_snippet_highlights_and_links(client, auth, db, stored):
    body = _get(client, auth, q='"material weakness" tariffs').json()
    (hit,) = body["hits"]
    assert hit["company"] == "Harbor Freight Example Corp" and hit["ticker"] is None
    assert hit["section"] == {"item": "10k:1A", "title": hit["section"]["title"]}
    assert hit["filing"]["form"] == "10-K" and hit["filing"]["filed_date"] == "2026-03-01"
    assert hit["filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    marked = {hit["snippet"][s:e].lower() for s, e in hit["highlights"]}
    assert marked == {"material weakness", "tariffs"}
    raw = str(body)
    for banned in ("first_detected_at", "source_updated_at", "fetched_at", "data.sec.gov"):
        assert banned not in raw
    cov = {c["section"]: c for c in body["coverage"]}
    assert cov["prospectus"]["sections"] == 2 and cov["prospectus"]["companies"] == 1
    assert cov["annual_report"]["items"] == ["10k:1A", "10k:7"]
    assert cov["earnings_release"]["first_filed"] == "2026-08-01"


def test_errors(client, auth, db, stored):
    for params, code in (({"q": "the of"}, "invalid_query"), ({"q": '"of the"'}, "invalid_query"),
                         ({"q": "x " + " ".join(f'"a{i} b"' for i in range(9))}, "invalid_query"),
                         ({"q": "tariffs", "cik": "abc"}, "invalid_parameter"),
                         ({"q": "tariffs", "form": "10K;DROP"}, "invalid_parameter"),
                         ({"q": "tariffs", "section": "nope"}, "invalid_parameter"),
                         ({"q": "tariffs", "filed_from": "2026-02-01", "filed_to": "2026-01-01"},
                          "invalid_parameter")):  # fmt: skip
        r = _get(client, auth, **params)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, params


def test_demo_key_showcase_only(client, db, stored, settings, monkeypatch):
    monkeypatch.setattr(settings, "public_showcase_ciks", "2999002")
    body = client.get("/v1/search/filings", params={"q": "tariffs"}, headers=DEMO).json()
    assert {h["cik"] for h in body["hits"]} == {"0002999002"}
    r = client.get("/v1/search/filings", params={"q": "tariffs", "cik": "2999001"}, headers=DEMO)
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_scope"
    # limit over 10 is trimmed, not refused (contract; the search page sends limit=20)
    monkeypatch.setattr(settings, "public_showcase_ciks", "2999001,2999002,2999003")
    wide = client.get("/v1/search/filings", params={"q": "tariffs", "limit": 20}, headers=DEMO)
    assert wide.status_code == 200 and wide.json()["meta"]["limit"] == 10
    assert len(wide.json()["hits"]) == 3
    # other endpoints keep the API-wide rule
    other = client.get("/v1/search", params={"q": "tariffs", "limit": 20}, headers=DEMO)
    assert other.status_code == 403 and other.json()["error"]["code"] == "demo_limit"


def test_parse_reads_websearch_syntax():
    q = fs.parse('"going concern" tariff or duties -china -"supply chain"')
    assert [[t.text for t in g] for g in q.groups] == [["going concern"], ["tariff", "duties"]]
    assert [t.text for t in q.excluded] == ["china", "supply chain"]
    with pytest.raises(fs.InvalidQuery):
        fs.parse("the and of")


def test_mcp_search_filings_calls_the_endpoint(client, auth, db, stored):
    import json

    args = {"query": '"going concern"', "as_of": "2026-12-31"}
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "search_filings", "arguments": args}}  # fmt: skip
    res = client.post("/mcp", json=body, headers=auth).json()["result"]
    assert res["isError"] is False
    out = json.loads(res["content"][0]["text"])
    assert _accs(out) == ["0002999001-26-000002"]
    assert out["query"]["filters"]["filed_to"] == "2026-12-31"


def test_chat_which_filings_mention(client, auth, db, stored):
    from app.services import conversation as cv

    assert cv.mention_request("Which filings mention supply chain disruption?")[0] == (
        "supply chain disruption")  # fmt: skip
    term, items, label, fam = cv.mention_request("Who talks about tariffs in their risk factors?")
    assert (term, items, label, fam) == ("tariffs", {"10k:1A", "pr:risk"}, "risk factors", None)
    assert cv.mention_request('Which companies mention "going concern" in 10-Ks?')[3] == (
        "annual_report")  # fmt: skip
    for other in ("What was Apple's revenue?", "Which companies filed a 10-K last month?",
                  "Who is the CEO of Tesla?"):  # fmt: skip
        assert cv.mention_request(other) is None, other
    r = client.post("/v1/chat", json={"message": 'Which filings mention "going concern"?'},
                    headers=auth).json()  # fmt: skip
    assert r["intent"] == "filing_search"
    (table,) = [w for w in r["widgets"] if w["type"] == "table"]
    assert [row[1]["text"] for row in table["rows"]] == ["S-1"]
    assert table["rows"][0][1]["url"].startswith("https://www.sec.gov/Archives/")
    assert r["citations"] and "going concern" in r["answer"]
    risk = client.post("/v1/chat", json={"message": "Who talks about tariffs in their risk "
                                         "factors?"}, headers=auth).json()  # fmt: skip
    (table,) = [w for w in risk["widgets"] if w["type"] == "table"]
    assert {row[3]["text"] for row in table["rows"]} == {
        "Risk factors",
        "10-K item 1A: Risk factors",
    }
    assert len(table["rows"]) == 2
    none = client.post("/v1/chat", json={"message": "Which filings mention zeppelins?"},
                       headers=auth).json()  # fmt: skip
    assert none["intent"] == "filing_search" and "covers only" in none["answer"]
