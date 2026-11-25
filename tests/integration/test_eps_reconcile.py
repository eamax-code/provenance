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


# S-06b: EPS triples about 1,000 or 1/100 off; the company's other filings name the one figure
CO2 = "0000000904"
A, B, C = "0000000904-24-000001", "0000000904-25-000001", "0000000904-26-000001"
P1, P2, P3 = (
    (date(2022, 1, 1), date(2022, 12, 31)),
    (date(2023, 1, 1), date(2023, 12, 31)),
    (date(2024, 1, 1), date(2024, 12, 31)),
)


def _nf2(metric, value, unit, period, acc, filed):
    tags = {"eps_diluted": "EarningsPerShareDiluted", "net_income": "NetIncomeLoss",
            "shares_diluted_weighted": "WeightedAverageNumberOfDilutedSharesOutstanding",
            "revenue": "Revenues"}  # fmt: skip
    f = _nf(metric, value, unit, period, acc, tags[metric])
    f.filed_date, f.form_type, f.source_taxonomy = filed, "10-K", "us-gaap"
    return f


def _setup_b(db):
    now = datetime.now(UTC)
    db.add(Company(cik=CO2, legal_name="SCALES INC", ticker="SCLS", fiscal_year_end="1231",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    db.flush()
    f24, f25, f26 = date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)
    facts = [
        # 2022, as filed in A (right) and in B (EPS 1,570 for 1.57, Barrett's shape)
        _nf2("eps_diluted", 1.57, "USD/shares", P1, A, f24),
        _nf2("net_income", 11_607_000, "USD", P1, A, f24),
        _nf2("shares_diluted_weighted", 7_408_000, "shares", P1, A, f24),
        _nf2("revenue", 100_000_000, "USD", P1, A, f24),
        _nf2("eps_diluted", 1570, "USD/shares", P1, B, f25),
        _nf2("net_income", 11_607_000, "USD", P1, B, f25),
        _nf2("shares_diluted_weighted", 7_408_000, "shares", P1, B, f25),
        # 2023, as filed in B (shares 1,000 times: Waters' shape) and in C (right)
        _nf2("eps_diluted", 2.00, "USD/shares", P2, B, f25),
        _nf2("net_income", 20_000_000, "USD", P2, B, f25),
        _nf2("shares_diluted_weighted", 10_000_000_000, "shares", P2, B, f25),
        _nf2("eps_diluted", 2.00, "USD/shares", P2, C, f26),
        _nf2("net_income", 20_000_000, "USD", P2, C, f26),
        _nf2("shares_diluted_weighted", 10_000_000, "shares", P2, C, f26),
        # 2024, net income in thousands (Palatin's shape) in C; right in a later filing D
        _nf2("eps_diluted", 0.25, "USD/shares", P3, C, f26),
        _nf2("net_income", 52_224, "USD", P3, C, f26),
        _nf2("shares_diluted_weighted", 208_896_000, "shares", P3, C, f26),
        _nf2("revenue", 300_000_000, "USD", P3, C, f26),
        _nf2("net_income", 52_224_000, "USD", P3, "0000000904-27-000001", date(2027, 3, 1)),
    ]
    upsert_facts(db, CO2, facts, now)
    return eps_reconcile.find_off(db, [CO2])


def test_the_other_filings_name_the_one_figure_off(db):
    found = {(f["accession_number"], f["metric"]): f for f in _setup_b(db)}
    assert set(found) == {(B, "eps_diluted"), (B, "shares_diluted_weighted"), (C, "net_income")}
    assert found[(B, "eps_diluted")]["factor"] == 1000.0
    assert found[(C, "net_income")]["factor"] == 0.001
    assert "about 1,000 times" in eps_reconcile.scale_note(found[(B, "eps_diluted")])
    note = eps_reconcile.scale_note(found[(C, "net_income")])
    assert "about 1/1,000 of" in note and "10-K filed 2027-03-01" in note


def test_a_lone_wrong_comparison_or_two_possible_fixes_flag_nothing(db):
    now = datetime.now(UTC)
    db.add(Company(cik=CO2, legal_name="SCALES INC", ticker="SCLS", fiscal_year_end="1231",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    db.flush()
    f25, f26 = date(2025, 3, 1), date(2026, 3, 1)
    upsert_facts(db, CO2, [
        # Landmark: this filing is right but its shares are 1,000x; the only other filing's net
        # income is the wrong one, so no single substitution reconciles
        _nf2("eps_diluted", 3.07, "USD/shares", P1, A, f25),
        _nf2("net_income", 18_775_000, "USD", P1, A, f25),
        _nf2("shares_diluted_weighted", 6_118_861_000, "shares", P1, A, f25),
        _nf2("net_income", 18_775, "USD", P1, B, f26),
        # Smith Midland: net income and shares both in thousands elsewhere: either would do
        _nf2("eps_diluted", 0.59, "USD/shares", P2, B, f26),
        _nf2("net_income", 3_129, "USD", P2, B, f26),
        _nf2("shares_diluted_weighted", 5_315_000, "shares", P2, B, f26),
        _nf2("net_income", 3_129_000, "USD", P2, C, f26),
        _nf2("shares_diluted_weighted", 5_315, "shares", P2, C, f26),
    ], now)  # fmt: skip
    assert eps_reconcile.find_off(db, [CO2]) == []


def test_flagged_figures_show_as_filed_with_notes_and_derived_cells_blank(client, auth, db):
    _setup_b(db)
    db.commit()
    url = f"/v1/companies/{CO2}/statements/income?period=annual"
    before = {r["metric"]: {c["column"]: c for c in r["cells"] if c}
              for r in client.get(url, headers=auth).json()["rows"]}  # fmt: skip
    assert before["eps_diluted"]["FY2022"]["value"] == 1570  # B, the latest filed, was shown
    assert eps_reconcile.apply(db, [CO2]) == 3
    db.commit()
    body = client.get(f"/v1/companies/{CO2}/statements/income?period=annual&include_derived=true",
                      headers=auth).json()  # fmt: skip
    rows = {r["metric"]: {c["column"]: c for c in r["cells"] if c} for r in body["rows"]}
    # 2024: the only 2024 net income in hand besides C's is D's, which is right and wins
    assert rows["net_income"]["FY2024"]["value"] == 52_224_000
    assert rows["net_margin"]["FY2024"]["value"] is not None
    # 2022: A's right EPS wins over B's flagged one
    assert rows["eps_diluted"]["FY2022"]["value"] == 1.57


def test_the_company_ingest_runs_the_check(db, sec_client, fake_sec, facts_aapl, monkeypatch):
    """Every company ingest flags what does not add up, in the same transaction (both rules: the
    100x EPS and the one figure the other filings show off)."""
    from app.services import ingestion

    calls = []
    real = eps_reconcile.apply
    monkeypatch.setattr(eps_reconcile, "apply", lambda d, ciks=None, found=None: calls.append(
        ciks) or real(d, ciks, found))  # fmt: skip
    fake_sec.add("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", facts_aapl)
    ingestion.ingest_company(db, sec_client, "320193")
    assert calls == [["0000320193"]]
