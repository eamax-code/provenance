"""Full-text search over stored filing sections (issue #2, step 2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.db.models import Company, Filing, FilingSection
from app.services import prospectus as pr
from app.services import section_search as ss

S1 = (Path(__file__).parents[1] / "fixtures" / "s1_example.htm").read_text(encoding="utf-8")
CIK = "0002999001"
ACCESSION = "0002999001-26-000002"
INDEX = (
    "https://www.sec.gov/Archives/edgar/data/2999001/000299900126000002/"
    + ACCESSION
    + "-index.html"
)


@pytest.fixture
def stored_s1(db):
    now = datetime.now(UTC)
    db.add(
        Company(
            cik=CIK, legal_name="Lumen Example Labs, Inc.", source_url=INDEX, first_detected_at=now
        )
    )
    db.add(
        Filing(
            cik=CIK,
            accession_number=ACCESSION,
            form_type="S-1",
            filing_date=date(2026, 10, 20),
            source_url=INDEX,
            first_detected_at=now,
            quality_status="ok",
        )
    )
    for item, text in pr.split_sections(S1).items():
        db.add(
            FilingSection(
                cik=CIK,
                accession_number=ACCESSION,
                item=item,
                status="ok",
                text=text,
                source_url=INDEX,
            )
        )
    db.commit()


def test_search_finds_the_section_and_cites_its_filing(db, stored_s1):
    hits = ss.search_sections(db, "cloud providers computing capacity")
    # The summary repeats the risk sentence, so either may rank first; both are found.
    assert {h.item for h in hits[:2]} == {"pr:risk", "pr:summ"}
    top = next(h for h in hits if h.item == "pr:risk")
    assert top.title == "Risk factors"
    assert (top.cik, top.accession_number, top.form_type) == (CIK, ACCESSION, "S-1")
    assert top.filing_date == date(2026, 10, 20) and top.source_url == INDEX
    assert "two cloud providers" in top.snippet and len(top.snippet.split()) <= ss.SNIPPET_WORDS
    assert 0 < top.rank <= ss.TITLE_BOOST


def test_a_query_that_names_a_section_lifts_it(db, stored_s1):
    hits = ss.search_sections(db, "use of proceeds")
    assert hits[0].item == "pr:use" and "$84.2 million" in hits[0].snippet


def test_filters_and_point_in_time(db, stored_s1):
    assert ss.search_sections(db, "computing capacity", as_of=date(2026, 10, 19)) == []
    assert ss.search_sections(db, "computing capacity", as_of=date(2026, 10, 20))
    assert ss.search_sections(db, "computing capacity", cik="0000320193") == []
    assert ss.search_sections(db, "computing capacity", forms=["10-K"]) == []
    assert ss.search_sections(db, "computing capacity", forms=["S-1", "S-1/A"])


def test_empty_and_unmatched_queries(db, stored_s1):
    assert ss.search_sections(db, "   ") == []
    assert ss.search_sections(db, "what is the") == []  # only stop words
    assert ss.search_sections(db, "zeppelin hovercraft") == []
    assert len(ss.search_sections(db, "the", limit=500)) == 0


def test_titles_and_snippets():
    assert ss.section_title("pr:owner") == "Principal stockholders"
    assert ss.section_title("ex:99.1") == "Earnings release (exhibit 99.1)"
    assert ss.section_title("5.02").startswith("8-K item 5.02")
    text = ("filler " * 200) + "the chief financial officer resigned in May " + ("filler " * 50)
    assert "officer resigned" in ss._snippet(text, ss._terms("chief financial officer resigned"))
    assert ss._terms("What are the risks?") == ["risk"]
