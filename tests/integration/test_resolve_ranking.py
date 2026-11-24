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


def test_dates_and_ticker_words_never_switch_a_given_company(db):
    """2026-11-24 (provenance-ui): an Ask link with cik and "filed 3 Nov 2026" was answered
    about NOV Inc. A month beside a day or year is a date; with a company given, only a name or
    a ticker in capitals switches it."""
    _co(db, "0000900120", "NOV Inc.", "NOV", 8_700_000_000)
    _co(db, "0000900121", "Apple Inc.", "AAPL", 400_000_000_000)
    db.commit()
    r = intel.resolve_company
    assert r(db, "What did the 10-Q filed 3 Nov 2026 say?") is None
    assert r(db, "What did the 10-Q filed 3 Nov 2026 say?", follow_up=True) is None
    assert r(db, "What did Apple report on Nov 3, 2026?").cik == "0000900121"
    assert r(db, "What did NOV Inc. file on 3 Nov 2026?").cik == "0000900120"
    assert r(db, "Nov revenue", follow_up=True) is None  # a ticker-shaped word: no switch
    assert r(db, "NOV revenue", follow_up=True).cik == "0000900120"  # a ticker in capitals


def test_short_tickers_resolve_only_as_the_subject(db):
    """2026-11-24 (provenance-pm, provenance-ui): one- and two-letter tickers (F, D, A, HP) are
    ordinary letters too. With a company given they never switch it; without one they resolve
    only as the subject ("F revenue", "$F", "Tell me about HP"), never after Form/Class/Item and
    never as a name's initial ("Robert F.")."""
    _co(db, "0000900130", "FORD MOTOR CO", "F", 180_000_000_000)
    _co(db, "0000900131", "DOMINION ENERGY, INC", "D", 14_000_000_000)
    _co(db, "0000900132", "AGILENT TECHNOLOGIES, INC.", "A", 6_500_000_000)
    _co(db, "0000900133", "Alphabet Inc.", "GOOGL", 400_000_000_000)
    _co(db, "0000900134", "Helmerich & Payne, Inc.", "HP", 2_700_000_000)
    db.commit()
    r = intel.resolve_company
    assert r(db, "F revenue").cik == "0000900130"
    assert r(db, "$F").cik == "0000900130"
    assert r(db, "What is Ford's revenue?").cik == "0000900130"
    assert r(db, "What is F stock doing?").cik == "0000900130"
    assert r(db, "Tell me about HP").cik == "0000900134"
    assert r(db, "Form D offerings") is None
    assert r(db, "Class A shares of Alphabet").cik == "0000900133"
    assert r(db, "Werner Robert F. Form 4", follow_up=True) is None
    assert r(db, "F revenue", follow_up=True) is None  # never switches from a given company
    assert r(db, "Form D offerings", follow_up=True) is None


def test_a_person_named_with_an_initial_is_never_a_company(db):
    """C-14 (2026-11-24): with no company given, "Werner Robert F." resolved to Robert Half, a
    first name that starts a company's name. A word in a person's name around an initial (as
    Forms 3, 4 and 144 give it) is never a company alone, nor a near spelling of one; a longer
    phrase still is (Robert W. Baird), and two initials make a company's name (J. B. Hunt)."""
    _co(db, "0000900140", "ROBERT HALF INC.", "RHI", 5_800_000_000)
    _co(db, "0000900141", "ROBERT W. BAIRD & CO. INCORPORATED", None, 4_000_000_000)
    _co(db, "0000900142", "WERNER ENTERPRISES INC", "WERN", 3_000_000_000)
    _co(db, "0000900143", "TIMOTHY PLAN", None, 1_000_000)
    _co(db, "0000900144", "HUNT J B TRANSPORT SERVICES INC", "JBHT", 12_000_000_000)
    _co(db, "0000900145", "BERKSHIRE HATHAWAY INC", "BRK-B", 370_000_000_000)
    db.commit()
    r = intel.resolve_company
    for q in ("Werner Robert F. Form 4", "What did Werner Robert F. sell?",
              "Form 144 filed by WERNER ROBERT F.", "Robert F. Werner Form 4",
              "Cook Timothy D sold shares", "J. Robert bought shares"):  # fmt: skip
        assert r(db, q) is None, q
    assert r(db, "Werner Robert F. sold Robert Half shares").cik == "0000900140"
    assert r(db, "Tell me about Robert Half").cik == "0000900140"
    assert r(db, "Robert W. Baird").cik == "0000900141"
    assert r(db, "Werner revenue").cik == "0000900142"
    assert r(db, "J. B. Hunt revenue").cik == "0000900144"
    assert r(db, "Berkshire Hathaway B shares").cik == "0000900145"
