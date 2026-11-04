"""Quick-answer marts (issue #8): one row per company and filing counts per month and form.

Built with window functions in SQL so a full rebuild reads the large tables once, and a rebuild
for a few companies after an ingestion run touches only their rows. Every figure keeps the filing
it came from (accession number and the filing's index page on sec.gov).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, cast, delete, distinct, func, insert, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    Filing,
    FinancialFact,
    MartCompany,
    MartFilingActivity,
)

REGISTRATION_FORMS = ("S-1", "F-1")
IPO_PROSPECTUS_FORMS = ("424B4",)
ANNUAL_REPORT_FORMS = ("10-K", "20-F", "40-F", "10-KT")
MART_METRICS = ("revenue", "net_income", "total_assets", "operating_income", "operating_cash_flow")
HISTORY_YEARS = 5
ACTIVITY_SINCE = date(2001, 1, 1)
BATCH = 2000


def build_company_marts(db: Session, ciks: list[str] | None = None) -> int:
    """Rebuild mart_company for these companies, or for every company. Returns rows written."""
    now = datetime.now(UTC)
    year_ago = now.date() - timedelta(days=365)
    scope = (lambda col: col.in_(ciks)) if ciks else (lambda col: True)  # noqa: E731

    companies = db.execute(
        select(
            Company.cik,
            Company.legal_name,
            Company.ticker,
            Company.exchange,
            Company.sic_code,
            Company.sic_description,
        ).where(scope(Company.cik))
    ).all()

    stats = {
        cik: (first, latest, int(recent or 0))
        for cik, first, latest, recent in db.execute(
            select(
                Filing.cik,
                func.min(Filing.filing_date),
                func.max(Filing.filing_date),
                func.sum(_case_count(Filing.filing_date >= year_ago)),
            )
            .where(scope(Filing.cik))
            .group_by(Filing.cik)
        )
    }
    registration = _first_filing(db, REGISTRATION_FORMS, scope)
    ipo = _first_filing(db, IPO_PROSPECTUS_FORMS, scope)
    annual_report = _latest_filing(db, ANNUAL_REPORT_FORMS, scope)
    metrics = _annual_metrics(db, scope)

    rows = []
    for cik, name, ticker, exchange, sic, sic_desc in companies:
        first, latest, recent = stats.get(cik, (None, None, 0))
        reg, prospectus, report = registration.get(cik), ipo.get(cik), annual_report.get(cik)
        series = metrics.get(cik, {})
        latest_annual = {m: points[0] for m, points in series.items() if points}
        revenue = series.get("revenue", [])
        rows.append(
            {
                "cik": cik,
                "legal_name": name,
                "ticker": ticker,
                "exchange": exchange,
                "sic_code": sic,
                "sic_description": sic_desc,
                "first_filing_date": first,
                "latest_filing_date": latest,
                "filings_last_12_months": recent,
                "active": recent > 0,
                "first_registration_date": reg["filing_date"] if reg else None,
                "first_registration_form": reg["form_type"] if reg else None,
                "ipo_prospectus_date": prospectus["filing_date"] if prospectus else None,
                "ipo_prospectus_accession": prospectus["accession"] if prospectus else None,
                "ipo_prospectus_url": prospectus["url"] if prospectus else None,
                "latest_annual_report_date": report["filing_date"] if report else None,
                "latest_annual_report_form": report["form_type"] if report else None,
                "latest_revenue": revenue[0]["value"] if revenue else None,
                "latest_revenue_period_end": (
                    date.fromisoformat(revenue[0]["period_end"]) if revenue else None
                ),
                "latest_annual": json.dumps(latest_annual, default=str) if latest_annual else None,
                "revenue_history": json.dumps(revenue, default=str) if revenue else None,
                "built_at": now,
            }
        )
    if ciks:
        db.execute(delete(MartCompany).where(MartCompany.cik.in_(ciks)))
    else:
        db.execute(delete(MartCompany))
    for i in range(0, len(rows), BATCH):
        db.execute(insert(MartCompany), rows[i : i + BATCH])
    db.commit()
    return len(rows)


def build_filing_activity(db: Session) -> int:
    """Rebuild mart_filing_activity: filings and distinct companies per month and form."""
    month = _month(Filing.filing_date, db)
    result = db.execute(
        select(month, Filing.form_type, func.count(), func.count(distinct(Filing.cik)))
        .where(Filing.filing_date >= ACTIVITY_SINCE)
        .group_by(month, Filing.form_type)
    ).all()
    db.execute(delete(MartFilingActivity))
    rows = [
        {
            "month": m if isinstance(m, date) else date.fromisoformat(str(m)[:10]),
            "form_type": form,
            "filings": int(n),
            "companies": int(c),
        }
        for m, form, n, c in result
        if m is not None and form
    ]
    for i in range(0, len(rows), BATCH):
        db.execute(insert(MartFilingActivity), rows[i : i + BATCH])
    db.commit()
    return len(rows)


def _case_count(condition):
    from sqlalchemy import case

    return case((condition, 1), else_=0)


def _month(column, db: Session):
    if db.get_bind().dialect.name == "postgresql":
        return cast(func.date_trunc("month", column), Date)
    return func.date(column, literal_column("'start of month'"))


def _ranked_filings(forms, scope, order):
    rank = func.row_number().over(partition_by=Filing.cik, order_by=order).label("rn")
    inner = (
        select(
            Filing.cik,
            Filing.form_type,
            Filing.filing_date,
            Filing.accession_number,
            Filing.source_url,
            rank,
        )
        .where(Filing.form_type.in_(forms), Filing.filing_date.is_not(None), scope(Filing.cik))
        .subquery()
    )
    return select(inner).where(inner.c.rn == 1)


def _filing_dict(row) -> dict:
    return {
        "form_type": row.form_type,
        "filing_date": row.filing_date,
        "accession": row.accession_number,
        "url": row.source_url,
    }


def _first_filing(db: Session, forms, scope) -> dict[str, dict]:
    stmt = _ranked_filings(forms, scope, [Filing.filing_date.asc(), Filing.accession_number])
    return {r.cik: _filing_dict(r) for r in db.execute(stmt)}


def _latest_filing(db: Session, forms, scope) -> dict[str, dict]:
    stmt = _ranked_filings(forms, scope, [Filing.filing_date.desc(), Filing.accession_number])
    return {r.cik: _filing_dict(r) for r in db.execute(stmt)}


def _annual_metrics(db: Session, scope) -> dict[str, dict[str, list[dict]]]:
    """Up to HISTORY_YEARS reported annual values per company and metric, newest first, one per
    period (the latest-filed observation), each with the filing it came from."""
    f = FinancialFact
    per_period = (
        func.row_number()
        .over(
            partition_by=(f.cik, f.metric, f.period_end),
            order_by=(f.filed_date.desc(), f.accession_number.desc()),
        )
        .label("rn")
    )
    observations = (
        select(
            f.cik,
            f.metric,
            f.value,
            f.unit,
            f.period_end,
            f.form_type,
            f.filed_date,
            f.accession_number,
            f.source_url,
            per_period,
        )
        .where(
            f.metric.in_(MART_METRICS),
            f.period_class == "annual",
            f.derived.is_(False),
            f.quality_status.in_(["ok", "partial"]),
            f.value.is_not(None),
            f.unit == "USD",
            scope(f.cik),
        )
        .subquery()
    )
    newest = (
        func.row_number()
        .over(
            partition_by=(observations.c.cik, observations.c.metric),
            order_by=observations.c.period_end.desc(),
        )
        .label("k")
    )
    ranked = select(observations, newest).where(observations.c.rn == 1).subquery()
    out: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in db.execute(
        select(ranked)
        .where(ranked.c.k <= HISTORY_YEARS)
        .order_by(ranked.c.cik, ranked.c.metric, ranked.c.k)
    ):
        out[r.cik][r.metric].append(
            {
                "value": float(r.value),
                "unit": r.unit,
                "period_end": r.period_end.isoformat(),
                "form_type": r.form_type,
                "filed_date": r.filed_date.isoformat() if r.filed_date else None,
                "accession": r.accession_number,
                "url": r.source_url,
            }
        )
    return out


def company_row(db: Session, cik: str) -> MartCompany | None:
    return db.get(MartCompany, cik)


def loads(text: str | None):
    return json.loads(text) if text else None
