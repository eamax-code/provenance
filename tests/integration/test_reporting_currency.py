"""D-04: marts, the company page and chat use each company's reporting currency, never a stale
convenience translation; sizes compare only within one currency."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Company, Filing, FinancialFact, utcnow
from app.services import company_overview, conversation, marts

EUR_CO, TWD_CO, USD_CO = "0000900001", "0000900002", "0000900003"


def _fact(cik, metric, value, unit, end, filed):
    key = hashlib.sha256(f"{cik}{metric}{unit}{end}".encode()).hexdigest()[:64]
    return FinancialFact(
        cik=cik, metric=metric, value=Decimal(value), unit=unit, currency=unit,
        period_start=date(end.year, 1, 1), period_end=end, period_type="duration",
        period_class="annual", fiscal_year=end.year, fiscal_period="FY", form_type="20-F",
        filed_date=filed, accession_number=f"{cik}-{end.year % 100:02d}-000001",
        source_tag="Revenue", source_taxonomy="ifrs-full",
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/x-index.html",
        mapping_version="1.4.0", quality_status="ok", derived=False, observation_key=key,
        first_detected_at=utcnow(), processed_at=utcnow(),
    )  # fmt: skip


@pytest.fixture
def three_currencies(db):
    for cik, name in ((EUR_CO, "Euro Software SE"), (TWD_CO, "Taiwan Chips Co Ltd"),
                      (USD_CO, "Dollar Software Inc")):  # fmt: skip
        db.add(Company(cik=cik, legal_name=name, sic_code="7372", source_url="https://www.sec.gov/",
                       first_detected_at=utcnow(), quality_status="ok",
                       fiscal_year_end="1231"))  # fmt: skip
        db.add(Filing(cik=cik, accession_number=f"{cik}-26-000009", form_type="20-F",
                      filing_date=date(2026, 3, 1), source_url="https://www.sec.gov/x-index.html",
                      first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    # EUR reporter whose only USD figure is a convenience translation from 2017
    db.add(_fact(EUR_CO, "revenue", 28_205_000_000, "USD", date(2017, 12, 31), date(2018, 3, 1)))
    for y, v in ((2023, 31_207_000_000), (2024, 34_176_000_000), (2025, 36_800_000_000)):
        db.add(_fact(EUR_CO, "revenue", v, "EUR", date(y, 12, 31), date(y + 1, 3, 1)))
    # TWD reporter with a USD translation of the same latest year
    for y, v in ((2023, 2_161_735_800_000), (2024, 2_894_307_700_000)):
        db.add(_fact(TWD_CO, "revenue", v, "TWD", date(y, 12, 31), date(y + 1, 4, 1)))
    db.add(_fact(TWD_CO, "revenue", 88_268_000_000, "USD", date(2024, 12, 31), date(2025, 4, 1)))
    db.add(_fact(USD_CO, "revenue", 9_000_000_000, "USD", date(2025, 12, 31), date(2026, 2, 1)))
    db.commit()
    marts.build_company_marts(db)
    marts.build_financial_marts(db)


def test_reporting_currency_is_the_latest_period_not_a_convenience_translation(
    db, three_currencies
):
    cur = marts.reporting_currencies(db)
    assert (cur[EUR_CO], cur[TWD_CO], cur[USD_CO]) == ("EUR", "TWD", "USD")


def test_page_shows_the_latest_year_in_the_reporting_currency(db, three_currencies):
    o = company_overview.build(db, EUR_CO, today=date(2026, 11, 22))
    rev = next(k for k in o["key_figures"] if k["metric"] == "revenue")
    assert (rev["value"], rev["currency"], rev["period_end"]) == (36.8e9, "EUR", "2025-12-31")
    assert rev["change_pct"] == pytest.approx(7.7, abs=0.05)
    assert o["company"]["reporting_currency"] == "EUR"
    assert [y["fiscal_year"] for y in o["years"]] == [2023, 2024, 2025]
    assert all(y["currency"] == "EUR" for y in o["years"])
    twd = company_overview.build(db, TWD_CO, today=date(2026, 11, 22))
    k = next(k for k in twd["key_figures"] if k["metric"] == "revenue")
    assert k["currency"] == "TWD" and k["value"] == 2_894_307_700_000


def test_peers_rank_within_one_currency_and_fill_unranked(db, three_currencies):
    o = company_overview.build(db, EUR_CO, today=date(2026, 11, 22))
    peers = o["peers"]["companies"]
    assert peers and all(not p["ranked"] for p in peers)  # no other EUR reporter
    assert {p["currency"] for p in peers} == {"TWD", "USD"}
    assert all(p["note"] == "different currency, not ranked by size" for p in peers)


def test_chat_prints_the_currency_and_ranks_usd_reporters_only(db, three_currencies):
    assert conversation._money(36.8e9, "EUR") == "EUR 36.8 billion"
    assert conversation._money(9e9, "USD") == "$9.0 billion"
    assert conversation._money(48_036_704_000_000, "JPY") == "JPY 48.0 trillion"
    p = conversation.Plan("rank", metric="revenue", limit=10)
    names = [row[0]["text"] for row in conversation._rank(db, p).widgets[0]["rows"]]
    assert names == ["Dollar Software Inc"]
    mart = db.get(conversation.MartCompany, EUR_CO)
    series = conversation._series(mart, "revenue")
    assert series[0]["unit"] == "EUR" and series[0]["period_end"] == "2025-12-31"


def test_chat_series_and_figures_use_the_reporting_unit(db, three_currencies):
    from app.services import intel
    from app.services.fact_normalizer import display_value

    series = intel.annual_series(db, EUR_CO, "revenue", None)
    assert [f.unit for f in series] == ["EUR", "EUR", "EUR"]
    assert series[0].period_end == date(2025, 12, 31)  # not the 2017 USD translation
    twd = intel.annual_series(db, TWD_CO, "revenue", None)
    assert {f.unit for f in twd} == {"TWD"}
    assert intel.money(36.8e9, "EUR") == "EUR 36.8 billion"
    assert display_value(Decimal("2.10"), "eps_diluted", "EUR/shares") == "EUR 2.10 per share"
    assert display_value(Decimal("6.08"), "eps_diluted", "USD/shares") == "$6.08 per share"


def test_profile_keeps_the_currency_code_in_capitals(db, three_currencies):
    from app.services import documents

    db.execute(__import__("sqlalchemy").text(
        "UPDATE mart_company SET latest_annual = :j WHERE cik = :c"),
        {"c": EUR_CO, "j": '{"revenue": {"value": 36800000000.0, "unit": "EUR", "period_end": '
         '"2025-12-31", "form_type": "20-F", "filed_date": "2026-03-01", "url": null}, '
         '"operating_income": {"value": 9600000000.0, "unit": "EUR", "period_end": "2025-12-31",'
         ' "form_type": "20-F", "filed_date": "2026-03-01", "url": null}}'})  # fmt: skip
    db.commit()
    p = documents.build_profile(db, EUR_CO, today=date(2026, 11, 22))
    assert "Operating income was EUR 9.6 billion" in p.summary
    assert "eur " not in p.summary
