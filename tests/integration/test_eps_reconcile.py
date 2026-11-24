"""S-06: EPS about 100 times the same filing's net income over weighted shares is flagged as
filed ("unit_doubtful"), never rescaled, and left out of derived uses."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Company, FinancialFact
from app.services import eps_reconcile
from app.services.fact_normalizer import NormalizedFact
from app.services.ingestion import upsert_facts

CIK = "0000000903"
ACC17, ACC18, ACC19 = "0000000903-18-000001", "0000000903-19-000001", "0000000903-20-000001"
Y17, Y18 = (date(2017, 1, 1), date(2017, 12, 31)), (date(2018, 1, 1), date(2018, 12, 31))
Y19 = (date(2019, 1, 1), date(2019, 12, 31))


def _nf(metric, value, unit, period, acc, tag):
    return NormalizedFact(metric=metric, value=Decimal(str(value)), unit=unit, currency="USD",
                          period_start=period[0], period_end=period[1], period_type="duration",
                          period_class="annual", fiscal_year=period[1].year, fiscal_period="FY",
                          form_type="20-F", filed_date=date(period[1].year + 1, 3, 1),
                          accession_number=acc, source_tag=tag, source_taxonomy="ifrs-full",
                          source_url=f"https://www.sec.gov/Archives/edgar/data/903/{acc}",
                          mapping_version="1.5.0", quality_status="ok")  # fmt: skip


def _facts():
    return [
        # 2017: Rio Tinto's shape, EPS in US cents tagged as dollars (8,762 / 1,799.5 = 4.87)
        _nf("eps_diluted", 486.919, "USD/shares", Y17, ACC17, "DilutedEarningsLossPerShare"),
        _nf("net_income", 8_762_000_000, "USD", Y17, ACC17, "ProfitLoss"),
        _nf("shares_diluted_weighted", 1_799_500_000, "shares", Y17, ACC17, "AdjustedWeighted"),
        # 2018: off by 30% (two share classes, preferred dividends): not a unit, left alone
        _nf("eps_diluted", 6.30, "USD/shares", Y18, ACC18, "DilutedEarningsLossPerShare"),
        _nf("net_income", 8_000_000_000, "USD", Y18, ACC18, "ProfitLoss"),
        _nf("shares_diluted_weighted", 1_650_000_000, "shares", Y18, ACC18, "AdjustedWeighted"),
        # 2019: 90x, outside the 5% band around 100: left alone, whatever the cause
        _nf("eps_diluted", 90.0, "USD/shares", Y19, ACC19, "DilutedEarningsLossPerShare"),
        _nf("net_income", 1_000_000_000, "USD", Y19, ACC19, "ProfitLoss"),
        _nf("shares_diluted_weighted", 1_000_000_000, "shares", Y19, ACC19, "AdjustedWeighted"),
    ]


def _setup(db):
    now = datetime.now(UTC)
    db.add(Company(cik=CIK, legal_name="CENTS PLC", ticker="CNTS", fiscal_year_end="1231",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    db.flush()
    upsert_facts(db, CIK, _facts(), now)
    return eps_reconcile.apply(db, [CIK])


def _status(db, metric, end):
    return db.scalar(select(FinancialFact.quality_status).where(
        FinancialFact.cik == CIK, FinancialFact.metric == metric,
        FinancialFact.period_end == end))  # fmt: skip


def test_only_the_100x_eps_is_flagged_and_a_reingest_keeps_it(db):
    assert _setup(db) == 1
    assert _status(db, "eps_diluted", Y17[1]) == "unit_doubtful"
    assert _status(db, "eps_diluted", Y18[1]) == "ok"  # 1.3x: not a unit
    assert _status(db, "eps_diluted", Y19[1]) == "ok"  # 90x: outside the band
    assert _status(db, "shares_diluted_weighted", Y17[1]) == "ok"  # only EPS carries a status
    upsert_facts(db, CIK, _facts(), datetime.now(UTC))  # the normalizer says "ok" again
    assert _status(db, "eps_diluted", Y17[1]) == "unit_doubtful"
    value = db.scalar(select(FinancialFact.value).where(
        FinancialFact.cik == CIK, FinancialFact.metric == "eps_diluted",
        FinancialFact.period_end == Y17[1]))  # fmt: skip
    assert float(value) == 486.919  # never rescaled


def test_statements_show_it_as_filed_with_a_note_on_eps_and_shares(client, auth, db):
    _setup(db)
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/statements/income?period=annual", headers=auth).json()
    rows = {r["metric"]: r for r in body["rows"]}
    eps = {c["column"]: c for c in rows["eps_diluted"]["cells"] if c}
    shares = {c["column"]: c for c in rows["shares_diluted_weighted"]["cells"] if c}
    assert eps["FY2017"]["value"] == 486.919 and eps["FY2017"]["quality_status"] == "unit_doubtful"
    assert "about 100 times" in eps["FY2017"]["quality_note"]
    assert shares["FY2017"]["quality_note"] == eps["FY2017"]["quality_note"]
    assert eps["FY2018"]["quality_note"] is None and eps["FY2018"]["quality_status"] == "ok"


def test_a_flagged_eps_never_makes_a_payout(client, auth, db):
    # $10 against 486.919 "dollars" would be a 0.02 payout, inside the 0.01-10 guard
    from app.db.models import DividendFact

    _setup(db)
    now = datetime.now(UTC)
    upsert_facts(db, CIK, [_nf("dividends_per_share", 10.0, "USD/shares", Y17, ACC17,
                               "CommonStockDividendsPerShareDeclared")], now,
                 model=DividendFact)  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/dividends", headers=auth).json()
    row = next(r for r in body["data"] if r["period_label"] == "FY2017")
    assert row["declared_per_share"] == 10.0 and row["payout_ratio"] is None
