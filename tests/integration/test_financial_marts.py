"""mart_financials and mart_company_period (issue #3, ADR 0009)."""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select

from app.db.models import FinancialFact, MartCompanyPeriod, MartFinancial
from app.services import marts


def _ingest_both(db, sec_client):
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "320193")
    ingest_company(db, sec_client, "789019")


def test_one_value_per_period_with_fiscal_labels(db, sec_client):
    _ingest_both(db, sec_client)
    rows, years = marts.build_financial_marts(db)
    assert rows > 0 and years > 0
    fy24 = db.get(MartFinancial, ("0000320193", "revenue", "annual", "USD", date(2024, 9, 28)))
    assert fy24.value == 391035000000 and fy24.fiscal_year == 2024 and fy24.form_type == "10-K"
    assert fy24.source_url.startswith("https://www.sec.gov/") and fy24.accession_number
    quarter = db.scalars(
        select(MartFinancial).where(
            MartFinancial.cik == "0000320193", MartFinancial.period_class == "quarterly"
        )
    ).first()
    assert quarter.fiscal_quarter in (1, 2, 3, 4)
    # No duplicate periods and no derived values.
    keys = db.execute(
        select(MartFinancial.cik, MartFinancial.metric, MartFinancial.period_class,
               MartFinancial.unit, MartFinancial.period_end)
    ).all()  # fmt: skip
    assert len(keys) == len(set(keys))
    wide = db.get(MartCompanyPeriod, ("0000320193", 2024))
    assert wide.revenue == 391035000000 and wide.period_end == date(2024, 9, 28)
    assert json.loads(wide.sources)["revenue"].startswith("https://www.sec.gov/")


def test_the_annual_report_wins_over_a_later_proxy_repeat(db, sec_client):
    _ingest_both(db, sec_client)
    ten_k = db.scalars(
        select(FinancialFact).where(
            FinancialFact.cik == "0000320193",
            FinancialFact.metric == "net_income",
            FinancialFact.period_class == "annual",
            FinancialFact.form_type == "10-K",
        )
    ).first()
    db.add(
        FinancialFact(
            **{
                c.name: getattr(ten_k, c.name)
                for c in FinancialFact.__table__.columns
                if c.name
                not in ("id", "form_type", "filed_date", "accession_number", "observation_key")
            },
            form_type="DEF 14A",
            filed_date=date(2099, 1, 1),
            accession_number="0000320193-99-000001",
            observation_key="proxy-repeat",
        )
    )
    db.commit()
    marts.build_financial_marts(db, ["0000320193"])
    row = db.get(
        MartFinancial, ("0000320193", "net_income", "annual", ten_k.unit, ten_k.period_end)
    )
    assert row.form_type == "10-K"


def test_the_screen_reads_the_mart_and_agrees_with_the_facts(client, auth, db, sec_client):
    _ingest_both(db, sec_client)
    url = "/v1/facts/screen?metric=total_assets&year=2024"
    from_facts = client.get(url, headers=auth).json()
    marts.build_financial_marts(db)
    from_mart = client.get(url, headers=auth).json()
    pick = lambda body: [(r["cik"], r["value"], r["period_end"]) for r in body["data"]]  # noqa: E731
    assert pick(from_mart) == pick(from_facts) and from_mart["meta"]["total_matched"] == 2
    asc = client.get(url + "&order=asc&limit=1", headers=auth).json()
    assert asc["data"][0]["cik"] == "0000320193" and asc["meta"]["has_more"] is True
    # A point-in-time screen still reads the observations.
    early = client.get(url + "&as_of=2020-01-01", headers=auth).json()
    assert early["data"] == [] and early["as_of"] == "2020-01-01"
