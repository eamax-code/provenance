"""Public, keyless showcase data for the website. Read-only, cached, never calls the SEC."""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import PUBLIC_PLANS, Settings, plan_limits
from app.core.timeutil import iso_z
from app.db.models import Company, Filing, FinancialFact
from app.schemas.companies import CompanyOut, FactOut, FilingOut, FreshnessOut
from app.schemas.public import (
    LatestFilingCard,
    LatestRevenueCard,
    PublicCompanyBundle,
    PublicMetricSeries,
    PublicPlan,
    PublicPlans,
    ShowcaseCompany,
    ShowcaseList,
)
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS
from app.services.freshness import company_freshness
from app.services.sec_client import normalize_cik

CACHE_TTL_SECONDS = 60
DISCLAIMER = (
    "Data from SEC EDGAR. Provenance is independent and not affiliated with or endorsed by "
    "the SEC. Missing values mean the SEC endpoint did not expose a mappable fact. "
    "Not investment advice."
)
METRIC_LABELS = {
    "revenue": "Revenue",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "operating_cash_flow": "Operating cash flow",
}
PERIODS_PER_METRIC = 8
FILINGS_PER_BUNDLE = 10

_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key: str, build):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    value = build()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def _now_iso() -> str:
    return iso_z(datetime.now(UTC)) or ""


# ---- plans --------------------------------------------------------------------------------


def public_plans(settings: Settings) -> PublicPlans:
    def build():
        out = []
        for entry in PUBLIC_PLANS:
            limits = plan_limits(entry["name"], settings)
            price = entry["price_usd_per_month"]
            out.append(
                PublicPlan(
                    name=entry["name"],
                    label=entry["label"],
                    featured=entry["featured"],
                    price_usd_per_month=price,
                    annual_price_usd_per_month=round(price * 10 / 12) if price else price,
                    rate_limit_per_minute=limits["rate_limit_per_minute"],
                    monthly_request_quota=limits["monthly_request_quota"],
                    max_watches=limits["max_watches"],
                    max_active_watches=limits["max_active_watches"],
                    max_export_rows=limits["max_export_rows"],
                )
            )
        return PublicPlans(
            data=out,
            max_export_rows=settings.max_export_rows,
            disclaimer=DISCLAIMER,
            generated_at=_now_iso(),
        )

    return _cached("plans", build)


# ---- showcase -----------------------------------------------------------------------------


def showcase_ciks(db: Session, settings: Settings) -> tuple[list[str], str]:
    """Return (ciks, source). Only ingested companies are ever exposed."""
    configured = [c.strip() for c in settings.public_showcase_ciks.split(",") if c.strip()]
    if configured:
        wanted: list[str] = []
        for raw in configured:
            try:
                cik = normalize_cik(raw)
            except ValueError:
                continue
            if cik not in wanted:
                wanted.append(cik)
        ingested = set(
            db.scalars(
                select(Company.cik).where(
                    Company.cik.in_(wanted), Company.last_processed_at.is_not(None)
                )
            )
        )
        return [c for c in wanted if c in ingested], "configured"
    latest_filing = (
        select(Filing.cik, func.max(Filing.filing_date).label("latest"))
        .group_by(Filing.cik)
        .subquery()
    )
    rows = db.execute(
        select(Company.cik)
        .join(latest_filing, latest_filing.c.cik == Company.cik, isouter=True)
        .where(Company.last_processed_at.is_not(None))
        .order_by(latest_filing.c.latest.desc().nulls_last(), Company.cik)
        .limit(max(0, settings.public_showcase_limit))
    ).all()
    return [r[0] for r in rows], "recent"


def _latest_filing(db: Session, cik: str) -> Filing | None:
    return db.scalar(
        select(Filing)
        .where(Filing.cik == cik)
        .order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
        .limit(1)
    )


def _annual_series(db: Session, cik: str, metric: str, limit: int) -> list[FinancialFact]:
    """Latest-filed ok/partial observation per annual period, newest first."""
    rows = db.scalars(
        select(FinancialFact).where(
            FinancialFact.cik == cik,
            FinancialFact.metric == metric,
            FinancialFact.period_class == "annual",
            FinancialFact.derived.is_(False),
            FinancialFact.quality_status.in_(["ok", "partial"]),
        )
    ).all()
    by_period: dict[tuple, FinancialFact] = {}
    for r in rows:
        key = (r.unit, r.period_start, r.period_end)
        cur = by_period.get(key)
        if cur is None or (r.filed_date or date.min, r.accession_number or "") > (
            cur.filed_date or date.min,
            cur.accession_number or "",
        ):
            by_period[key] = r
    ordered = sorted(by_period.values(), key=lambda r: r.period_end, reverse=True)
    return ordered[:limit]


def _revenue_card(db: Session, cik: str) -> LatestRevenueCard | None:
    facts = _annual_series(db, cik, "revenue", 1)
    if not facts:
        return None
    f = facts[0]
    return LatestRevenueCard(
        value=f.value,
        unit=f.unit,
        currency=f.currency,
        period_start=f.period_start.isoformat() if f.period_start else None,
        period_end=f.period_end.isoformat(),
        fiscal_year=f.fiscal_year,
        form_type=f.form_type,
        filed_date=f.filed_date.isoformat() if f.filed_date else None,
        accession_number=f.accession_number,
        source_tag=f.source_tag,
        source_url=f.source_url,
        quality_status=f.quality_status,
    )


def public_companies(db: Session, settings: Settings) -> ShowcaseList:
    def build():
        ciks, source = showcase_ciks(db, settings)
        companies = (
            {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(ciks)))}
            if ciks
            else {}
        )
        cards = []
        for cik in ciks:
            c = companies.get(cik)
            if c is None:
                continue
            lf = _latest_filing(db, cik)
            cards.append(
                ShowcaseCompany(
                    cik=c.cik,
                    legal_name=c.legal_name,
                    ticker=c.ticker,
                    exchange=c.exchange,
                    sic_description=c.sic_description,
                    last_processed_at=iso_z(c.last_processed_at),
                    filings_count=int(
                        db.scalar(select(func.count(Filing.id)).where(Filing.cik == cik)) or 0
                    ),
                    facts_count=int(
                        db.scalar(
                            select(func.count(FinancialFact.id)).where(FinancialFact.cik == cik)
                        )
                        or 0
                    ),
                    latest_filing=LatestFilingCard(
                        form_type=lf.form_type,
                        filing_date=lf.filing_date.isoformat() if lf.filing_date else None,
                        accession_number=lf.accession_number,
                        source_url=lf.source_url,
                    )
                    if lf
                    else None,
                    latest_annual_revenue=_revenue_card(db, cik),
                )
            )
        return ShowcaseList(
            data=cards,
            meta={
                "showcase_source": source,
                "limit": settings.public_showcase_limit,
                "count": len(cards),
            },
            generated_at=_now_iso(),
            disclaimer=DISCLAIMER,
        )

    return _cached("companies", build)


def company_bundle(db: Session, settings: Settings, cik: str) -> PublicCompanyBundle | None:
    cik = normalize_cik(cik)

    def build():
        ciks, _ = showcase_ciks(db, settings)
        if cik not in ciks:
            return None
        company = db.scalar(select(Company).where(Company.cik == cik))
        if company is None or company.last_processed_at is None:
            return None
        filings = db.scalars(
            select(Filing)
            .where(Filing.cik == cik)
            .order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
            .limit(FILINGS_PER_BUNDLE)
        ).all()
        series = []
        for metric in SUPPORTED_METRICS:
            facts = _annual_series(db, cik, metric, PERIODS_PER_METRIC)
            if facts:
                status, note = "ok", "Latest-filed annual observation per period."
            else:
                has_ambiguous = db.scalar(
                    select(FinancialFact.id)
                    .where(
                        FinancialFact.cik == cik,
                        FinancialFact.metric == metric,
                        FinancialFact.quality_status.in_(
                            ["ambiguous_mapping", "invalid_source_value"]
                        ),
                    )
                    .limit(1)
                )
                if has_ambiguous is not None:
                    status = "ambiguous_mapping"
                    note = (
                        "Candidate XBRL tags disagree or values could not be parsed; shown only "
                        "with a key via include_all_observations."
                    )
                else:
                    status = "unavailable"
                    note = (
                        "The SEC company-facts API exposed no mappable standard tag for this "
                        "metric. The issuer may still report it under a custom tag."
                    )
            series.append(
                PublicMetricSeries(
                    metric=metric,
                    label=METRIC_LABELS[metric],
                    status=status,
                    note=note,
                    facts=[FactOut.model_validate(f) for f in facts],
                )
            )
        fresh = FreshnessOut(**company_freshness(db, company, settings))
        return PublicCompanyBundle(
            company=CompanyOut.model_validate(company),
            filings=[FilingOut.model_validate(f) for f in filings],
            metrics=series,
            freshness=fresh,
            mapping_version=MAPPING_VERSION,
            notes=[
                DISCLAIMER,
                "Annual series only; quarterly and derived values require an API key.",
                "period_class comes from the reported period dates, not the SEC fiscal-period "
                "label.",
            ],
            generated_at=_now_iso(),
        )

    return _cached(f"company:{cik}", build)
