"""K-05: a company that continues under a new holding company keeps one history; each row keeps
the registrant that filed it."""

from __future__ import annotations

from datetime import date

import pytest

from app.db.models import Company, Filing, utcnow
from app.services import successions

OLD, NEW = "0000320193", "0009999991"
DAY = date(2026, 7, 1)


def _filing(cik, acc, form, day, items=None):
    return Filing(cik=cik, accession_number=acc, form_type=form, filing_date=day, items=items,
                  source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}-index.html",
                  first_detected_at=utcnow(), quality_status="ok")  # fmt: skip


@pytest.fixture
def reorganised(db, ingested_aapl):
    db.add(Company(cik=NEW, legal_name="Apple Holdings, Inc.", ticker="AAPL",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow(),
                   quality_status="ok"))  # fmt: skip
    db.add(_filing(NEW, "0009999991-26-000001", "8-K12B", DAY, "2.01,3.03,5.03"))
    db.add(_filing(OLD, "0000320193-26-000900", "25-NSE", date(2026, 7, 2)))
    # a different company delisting the same day is not a match
    db.add(Company(cik="0009999992", legal_name="Banana Corp", source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.add(_filing("0009999992", "0009999992-26-000001", "25-NSE", DAY))
    db.commit()


def test_name_key():
    assert successions.name_key("ExxonMobil Holdings Corp") == successions.name_key(
        "EXXON MOBIL CORP"
    )
    assert successions.name_key("Six Flags Entertainment Corp/OLD") == successions.name_key(
        "Six Flags Entertainment Corporation/NEW"
    )
    assert successions.name_key("Apple Inc.") != successions.name_key("Banana Corp")


def test_detect_and_store(db, reorganised):
    pairs = successions.detect(db)
    assert [(p["predecessor_cik"], p["successor_cik"]) for p in pairs] == [(OLD, NEW)]
    p = pairs[0]
    assert p["effective_date"] == DAY and p["evidence_form"] == "8-K12B"
    assert p["predecessor_form"] == "25-NSE" and p["confidence"] == "high"
    assert successions.store(db, pairs) == 1 and successions.store(db, pairs) == 0
    assert [r.predecessor_cik for r in successions.predecessors(db, NEW)] == [OLD]
    assert successions.successor(db, OLD).successor_cik == NEW


def test_successor_overview_continues_the_history(db, reorganised):
    successions.store(db, successions.detect(db))
    from app.services import company_overview

    o = company_overview.build(db, NEW)
    assert company_overview.first_filing_date(db, NEW) < DAY  # as_of reaches the old filings
    pred = o["company"]["predecessors"]
    assert pred[0]["cik"] == OLD and pred[0]["evidence"]["form_type"] == "8-K12B"
    assert pred[0]["evidence"]["source_url"].endswith("0009999991-26-000001-index.html")
    income = next(s for s in o["statements"]["sections"] if s["key"] == "income")
    cells = [c for row in income["rows"] for c in row["cells"] if c]
    assert cells and all(c["registrant_cik"] == OLD and c["predecessor"] for c in cells)
    assert cells[0]["registrant_label"] == "Reported by predecessor registrant (CIK 320193)"
    assert all(c["source_url"].startswith("https://www.sec.gov/") for c in cells)
    old = company_overview.build(db, OLD)
    assert old["company"]["successor"]["cik"] == NEW
    own = next(s for s in old["statements"]["sections"] if s["key"] == "income")
    assert all(not c["predecessor"] for row in own["rows"] for c in row["cells"] if c)
