"""X-19 peers on the overview (U-02): same accounting basis, a 0.1x-10x revenue band with the
industry widened only to fill it, one registrant per group, a successor in place of its
predecessor, and each peer's revenue with its filing."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Company, Filing, FinancialFact, RegistrantSuccession, utcnow
from app.services import company_overview, marts

TODAY = date(2026, 11, 24)
ME = "0000800001"
CO = {  # cik: (name, sic, taxonomy, revenue in billions)
    ME: ("ME COMPUTERS INC", "3571", "us-gaap", 400),
    "0000800002": ("NEAR ONE INC", "3571", "us-gaap", 100),
    "0000800003": ("BIG GROUP HOLDINGS INC", "3571", "us-gaap", 90),
    "0000800004": ("BIG INC", "3571", "us-gaap", 80),  # same group as the one above
    "0000800005": ("IFRS COMPUTERS SE", "3571", "ifrs-full", 300),  # other accounting basis
    "0000800006": ("TINY CO", "3571", "us-gaap", 1),  # outside the band
    "0000800007": ("STORAGE CORP", "3572", "us-gaap", 60),
    "0000800008": ("TERMINALS CORP", "3575", "us-gaap", 70),
    "0000800009": ("OLD NAME CORP", "3576", "us-gaap", 50),  # has a successor
    "0000800010": ("NEW HOLDCO INC", "3576", None, None),  # the successor, no revenue yet
}


def _fact(cik, value, taxonomy):
    end = date(2025, 12, 31)
    key = hashlib.sha256(f"{cik}revenue{end}".encode()).hexdigest()[:64]
    return FinancialFact(
        cik=cik, metric="revenue", value=Decimal(value), unit="USD", currency="USD",
        period_start=date(2025, 1, 1), period_end=end, period_type="duration",
        period_class="annual", fiscal_year=2025, fiscal_period="FY", form_type="10-K",
        filed_date=date(2026, 2, 20), accession_number=f"{cik}-26-000001",
        source_tag="Revenues", source_taxonomy=taxonomy,
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/x-index.html",
        mapping_version="1.5.0", quality_status="ok", derived=False, observation_key=key,
        first_detected_at=utcnow(), processed_at=utcnow(),
    )  # fmt: skip


@pytest.fixture
def industry(db):
    for cik, (name, sic, tax, rev) in CO.items():
        db.add(Company(cik=cik, legal_name=name, sic_code=sic, source_url="https://www.sec.gov/",
                       first_detected_at=utcnow(), quality_status="ok",
                       fiscal_year_end="1231"))  # fmt: skip
        db.add(Filing(cik=cik, accession_number=f"{cik}-26-000001", form_type="10-K",
                      filing_date=date(2026, 2, 20),
                      source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/x-index.html",
                      first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
        if rev:
            db.add(_fact(cik, rev * 1_000_000_000, tax))
    db.add(RegistrantSuccession(
        predecessor_cik="0000800009", successor_cik="0000800010", effective_date=date(2026, 6, 1),
        evidence_accession="0000800010-26-000002", evidence_form="8-K12B",
        match_method="reviewed", confidence="high"))  # fmt: skip
    db.commit()
    marts.build_company_marts(db)
    marts.build_financial_marts(db)


def test_peers_basis_band_groups_and_successor(db, industry):
    p = company_overview.build(db, ME, today=TODAY)["peers"]
    names = [c["name"] for c in p["companies"]]
    # 3571 alone has three peers in the band, so the industry widens to 357 (once, not to 35)
    assert p["basis_width"] == 3 and p["sic"] == "357"
    assert "Ifrs Computers SE" not in names  # IFRS filer, this company reports under US GAAP
    assert "Tiny Co" not in names  # 1/400 of the revenue: outside the band
    assert sum(n.startswith("Big") for n in names) == 1  # one registrant per group
    assert names[0] == "Near One Inc"  # nearest in size first
    succ = next(c for c in p["companies"] if c["cik"] == "0000800010")
    assert succ["name"] == "New Holdco Inc" and succ["revenue_reported_by"]["cik"] == "0000800009"
    assert all(c["cik"] != "0000800009" for c in p["companies"])  # the predecessor gives way
    first = p["companies"][0]
    assert first["accounting"] == "us-gaap" and first["form_type"] == "10-K"
    assert first["accession_number"] == "0000800002-26-000001"
    assert first["source_url"].startswith("https://www.sec.gov/Archives/")
    assert first["is_public_page"] is False and first["filed_date"]
    assert p["basis"].endswith("nearest in size first; one registrant per group.")
    assert "US GAAP" in p["basis"] and p["accounting"] == "us-gaap"
    assert p["revenue_band"] == [40e9, 4000e9]


def test_a_successor_without_revenue_is_sized_by_its_predecessor(db, industry):
    p = company_overview.build(db, "0000800010", today=TODAY)["peers"]
    assert p["sized_by_predecessor"] == "0000800009" and p["revenue_band"] == [5e9, 500e9]
    assert all(c["cik"] not in ("0000800009", "0000800010") for c in p["companies"])
    assert "(as last reported by its predecessor)" in p["basis"]
