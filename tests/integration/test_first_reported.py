"""E-2: a figure counts as first reported in an earnings release only when the release states
the same value on a line labelled for the metric; as_of then counts it from the release date."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Filing, FilingSection, FinancialFact, FirstReported, utcnow
from app.services import first_reported as fr

CIK = "0000320193"
URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019399000001/ex991.htm"


def test_renderings_and_line_rules():
    v = Decimal("94930000000")
    text = "Net sales: | | \nTotal net sales | $ 94,930 | $ 89,498\nCost of sales | 52,000 | 48,000"
    assert fr.stated(text, "revenue", v) == ("millions", "Total net sales | $ 94,930 | $ 89,498")
    # the number on another metric's line, or a different value, is not a statement
    assert fr.stated("Cost of sales | $ 94,930", "revenue", v) is None
    assert fr.stated("Total net sales | $ 94,931", "revenue", v) is None
    assert fr.stated("Total net sales | $ 194,930", "revenue", v) is None
    # thousands, losses in parentheses, billions in the text, per-share to the cent
    assert fr.stated("Net loss | (1,234,567) | (900)", "net_income",
                     Decimal("-1234567000"))[0] == "thousands"  # fmt: skip
    assert fr.stated("Revenue grew to $94.93 billion this quarter", "revenue", v)[0] == "billions"
    assert fr.stated("Diluted | $ 1.64 | $ 1.46", "eps_diluted", Decimal("1.64")) == (
        "per share", "Diluted | $ 1.64 | $ 1.46")
    assert fr.stated("Diluted | 15,550,061", "eps_diluted", Decimal("1.64")) is None
    # in a paragraph the label must come just before the number
    near = "Apple announced diluted earnings per share of $1.64, up 12 percent."
    assert fr.stated(near, "eps_diluted", Decimal("1.64"))[0] == "per share"
    far = "Diluted shares fell. " + "x" * 120 + " The dividend is $1.64 per share."
    assert fr.stated(far, "eps_diluted", Decimal("1.64")) is None
    assert fr.stated("Net cash from operations | 35,758 | 22,291", "operating_cash_flow",
                     Decimal("35758000000"))[0] == "millions"  # fmt: skip
    # a long table row: the evidence still shows the number
    row = ("Cash and cash equivalents | " + " | ".join(["  9,999  "] * 60) + " | $  3,369 | x")
    found = fr.stated(row, "cash_and_equivalents", Decimal("3369000000"))
    assert found and "3,369" in found[1] and found[1].startswith("Cash and cash equivalents")
    # fewer than four digits as printed never match
    assert fr.renderings(Decimal("120000000"), "revenue")[0][1] != "millions"
    assert fr.stated("Total revenue | $ 120 | $ 98", "revenue", Decimal("120000000")) is None


@pytest.fixture
def release(db, ingested_aapl):
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.cik == CIK, FinancialFact.metric == "revenue",
            FinancialFact.period_class == "quarterly", FinancialFact.form_type == "10-Q",
            FinancialFact.derived.is_(False), FinancialFact.quality_status == "ok",
        ).order_by(FinancialFact.period_end.desc())
    )  # fmt: skip
    assert fact is not None
    released = fact.filed_date - timedelta(days=7)
    assert released > fact.period_end
    acc = "0000320193-99-000001"
    db.add(Filing(cik=CIK, accession_number=acc, form_type="8-K", filing_date=released,
                  items="2.02,9.01", source_url=URL, first_detected_at=utcnow(),
                  quality_status="ok"))  # fmt: skip
    millions = int((fact.value / Decimal(10**6)).quantize(Decimal(1)))
    text = (f"Apple reports results\nTotal net sales | $ {millions:,} | $ 1,234\n"
            f"Cost of sales | 9,999 | 8,888")  # fmt: skip
    db.add(FilingSection(cik=CIK, accession_number=acc, item="ex:99.1", status="ok", text=text,
                         source_url=URL, fetched_at=utcnow()))  # fmt: skip
    db.commit()
    return fact, released


def test_match_records_evidence_and_is_idempotent(db, release):
    fact, released = release
    assert fr.match_company(db, CIK) >= 1
    row = db.scalar(
        select(FirstReported).where(
            FirstReported.fact_accession == fact.accession_number,
            FirstReported.metric == "revenue",
            FirstReported.period_end == fact.period_end,
        )
    )
    assert row.release_filing_date == released and row.stated_as == "millions"
    assert row.evidence.startswith("Total net sales") and row.release_url == URL
    assert fr.match_company(db, CIK) == 0  # nothing new


def test_facts_api_shows_first_reported_and_as_of_counts_from_the_release(
    db, client, auth, release
):
    fact, released = release
    fr.match_company(db, CIK)
    q = "/v1/companies/320193/facts?metric=revenue&period=quarterly&limit=100"
    rows = client.get(q, headers=auth).json()["data"]
    hit = next(r for r in rows if r["period_end"] == fact.period_end.isoformat()
               and r["period_start"] == fact.period_start.isoformat())  # fmt: skip
    assert hit["first_reported"]["filing_date"] == released.isoformat()
    assert hit["first_reported"]["source_url"] == URL
    # on the release day the figure is known, though the 10-Q came a week later
    day = released.isoformat()
    known = client.get(f"{q}&as_of={day}", headers=auth).json()["data"]
    assert any(r["period_end"] == fact.period_end.isoformat() for r in known)
    before = (released - timedelta(days=1)).isoformat()
    earlier = client.get(f"{q}&as_of={before}", headers=auth).json()["data"]
    same = [r for r in earlier if r["period_end"] == fact.period_end.isoformat()]
    assert not any(r["period_start"] == fact.period_start.isoformat() for r in same)


def test_release_after_the_10q_or_with_another_value_is_not_first_reported(db, release):
    fact, _ = release
    sec = db.scalar(select(FilingSection).where(FilingSection.item == "ex:99.1"))
    sec.text = "Total net sales | $ 1,111 | $ 1,234"
    db.commit()
    assert fr.match_company(db, CIK) == 0


def test_a_comparative_is_never_first_reported(db, release):
    """A prior period repeated in a later filing was known from its own filing already."""
    from datetime import date

    fact, _ = release
    assert fr.original(fact, fact.period_end)
    assert not fr.original(fact, date(2099, 1, 1))  # the filing covers another period


def test_match_rates_count_matched_of_eligible(db, release):
    fr.match_company(db, CIK)
    rates = fr.match_rates(db)
    matched, eligible = rates["revenue"]
    assert matched >= 1 and eligible >= matched
