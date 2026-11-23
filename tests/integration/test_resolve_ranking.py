"""Chat and the palette resolve a bare company word to the company people mean (2026-11-24):
a capitalised word that is a company's ticker and starts its name wins ("Meta" is META), and
between names that start the same way the larger filer wins."""

from __future__ import annotations

from decimal import Decimal

from app.db.models import Company, MartCompany, utcnow
from app.services import intel


def _co(db, cik, name, ticker, revenue):
    db.add(Company(cik=cik, legal_name=name, ticker=ticker, source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.add(MartCompany(cik=cik, legal_name=name, ticker=ticker,
                       latest_revenue=Decimal(revenue) if revenue else None,
                       reporting_currency="USD", built_at=utcnow()))  # fmt: skip


def test_ticker_word_and_size_decide(db):
    _co(db, "0000900101", "Meta Data Ltd", None, None)
    _co(db, "0000900102", "Meta Platforms, Inc.", "META", 200_000_000_000)
    _co(db, "0000900103", "Snap-on Inc", "SNA", 5_000_000_000)
    _co(db, "0000900104", "Snap Inc", "SNAP", 5_500_000_000)
    _co(db, "0000900105", "Honeywell Aerospace Inc.", "HONA", 15_000_000_000)
    _co(db, "0000900106", "Honeywell International Inc", "HON", 38_000_000_000)
    db.commit()
    assert intel.resolve_company(db, "Meta revenue").cik == "0000900102"
    assert intel.resolve_company(db, "Tell me about Snap").cik == "0000900104"
    assert intel.resolve_company(db, "Honeywell revenue").cik == "0000900106"
    assert intel.resolve_company(db, "Snap-on revenue").cik == "0000900103"  # its own name
