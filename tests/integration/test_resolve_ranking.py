"""Chat resolves a bare company word to the company people mean (2026-11-24): a capitalised
word that is a company's ticker and starts its name wins ("Meta"); an active registrant beats
one with no annual report in two years, and an inactive one with a K-05 successor resolves to
the successor, saying so ("Google"); punctuation does not matter ("Coca-Cola"); the larger
filer wins between names that start alike; a whole word inside a name is the last resort
("Disney"), never a generic word ("Software")."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import Company, MartCompany, RegistrantSuccession, utcnow
from app.services import intel

RECENT, OLD = date.today() - timedelta(days=60), date(2014, 3, 1)


def _co(db, cik, name, ticker, revenue, annual=RECENT):
    db.add(Company(cik=cik, legal_name=name, ticker=ticker, source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.add(MartCompany(cik=cik, legal_name=name, ticker=ticker,
                       latest_revenue=Decimal(revenue) if revenue else None,
                       reporting_currency="USD", latest_annual_report_date=annual,
                       built_at=utcnow()))  # fmt: skip


def test_ticker_word_size_activity_and_successor(db):
    _co(db, "0000900101", "Meta Data Ltd", None, None)
    _co(db, "0000900102", "Meta Platforms, Inc.", "META", 200_000_000_000)
    _co(db, "0000900103", "Snap-on Inc", "SNA", 5_000_000_000)
    _co(db, "0000900104", "Snap Inc", "SNAP", 5_500_000_000)
    _co(db, "0000900105", "Honeywell Aerospace Inc.", "HONA", 15_000_000_000)
    _co(db, "0000900106", "Honeywell International Inc", "HON", 38_000_000_000)
    _co(db, "0000900107", "GOOGLE INC.", None, None, OLD)
    _co(db, "0000900108", "Alphabet Inc.", "GOOGL", 400_000_000_000)
    _co(db, "0000900109", "LUCID INC", None, None, OLD)
    _co(db, "0000900110", "Lucid Group, Inc.", "LCID", 1_000_000_000)
    _co(db, "0000900111", "PEPSI BOTTLING GROUP INC", None, None, OLD)
    _co(db, "0000900112", "PEPSICO INC", "PEP", 90_000_000_000)
    _co(db, "0000900113", "Coca-Cola Consolidated, Inc.", "COKE", 7_000_000_000)
    _co(db, "0000900114", "COCA COLA CO", "KO", 47_000_000_000)
    _co(db, "0000900115", "Walt Disney Co", "DIS", 94_000_000_000)
    _co(db, "0000900116", "TAKE TWO INTERACTIVE SOFTWARE INC", "TTWO", 5_000_000_000)
    db.add(RegistrantSuccession(
        predecessor_cik="0000900107", successor_cik="0000900108", effective_date=date(2015, 10, 2),
        evidence_accession="0001193125-15-336550", evidence_form="8-K",
        match_method="holding_company_reorganization", confidence="high"))  # fmt: skip
    db.commit()
    r = intel.resolve_company
    assert r(db, "Meta revenue").cik == "0000900102"
    assert r(db, "Tell me about Snap").cik == "0000900104"
    assert r(db, "Honeywell revenue").cik == "0000900106"
    assert r(db, "Snap-on revenue").cik == "0000900103"  # its own name
    notes: list[str] = []
    assert r(db, "Google revenue", notes=notes).cik == "0000900108"
    assert notes == ["Google Inc. is now Alphabet Inc., its successor registrant since 2015-10-02."]
    assert r(db, "Lucid revenue").cik == "0000900110"  # active beats inactive
    assert r(db, "Pepsi revenue").cik == "0000900112"  # the bottler is inactive
    assert r(db, "Coca-Cola revenue").cik == "0000900114"  # punctuation does not matter
    assert r(db, "Disney revenue").cik == "0000900115"  # a whole word inside the name
    assert r(db, "Software companies over $1B revenue") is None  # a generic word names no one
