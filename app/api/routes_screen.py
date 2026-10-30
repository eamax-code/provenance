"""Cross-company screen: one normalized metric for every company, for one year."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.core.errors import APIError
from app.db.models import Company, FinancialFact
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.public import LatestRevenueCard
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS

router = APIRouter(prefix="/v1/facts", tags=["facts"])


class ScreenRow(LatestRevenueCard):
    cik: str
    legal_name: str
    ticker: str | None
    exchange: str | None
    metric: str
    mapping_version: str


class ScreenResult(BaseModel):
    metric: str
    year: int
    period: str
    unit: str
    data: list[ScreenRow]
    meta: PageMeta
    notes: list[str]


@router.get(
    "/screen",
    response_model=ScreenResult,
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    summary="Rank one metric across all companies for a year",
)
def screen(
    metric: str = Query(..., description=", ".join(SUPPORTED_METRICS)),
    year: int = Query(..., ge=1990, le=2100, description="Calendar year of period_end"),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    unit: str = Query("USD", max_length=20),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    if metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    rows = db.scalars(
        select(FinancialFact).where(
            FinancialFact.metric == metric,
            FinancialFact.period_class == period,
            FinancialFact.unit == unit,
            FinancialFact.derived.is_(False),
            FinancialFact.quality_status.in_(["ok", "partial"]),
            FinancialFact.value.is_not(None),
            FinancialFact.period_end >= date(year, 1, 1),
            FinancialFact.period_end <= date(year, 12, 31),
        )
    ).all()
    # Per company: the latest period ending in the year, then the latest-filed observation.
    best: dict[str, FinancialFact] = {}
    for f in rows:
        cur = best.get(f.cik)
        key = (f.period_end, f.filed_date or date.min, f.accession_number or "")
        if cur is None or key > (
            cur.period_end,
            cur.filed_date or date.min,
            cur.accession_number or "",
        ):
            best[f.cik] = f
    companies = (
        {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(list(best))))}
        if best
        else {}
    )
    ranked = sorted(best.values(), key=lambda f: (f.value, f.cik), reverse=(order == "desc"))
    page = ranked[offset : offset + limit]
    out = []
    for f in page:
        c = companies.get(f.cik)
        out.append(
            ScreenRow(
                cik=f.cik,
                legal_name=c.legal_name if c else "",
                ticker=c.ticker if c else None,
                exchange=c.exchange if c else None,
                metric=f.metric,
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
                mapping_version=f.mapping_version or MAPPING_VERSION,
            )
        )
    has_more = offset + limit < len(ranked)
    return ScreenResult(
        metric=metric,
        year=year,
        period=period,
        unit=unit,
        data=out,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
            total_matched=len(ranked),
        ),
        notes=[
            "One row per company: the latest reported period whose period_end falls in the "
            "requested calendar year, using the latest-filed preferred observation.",
            "Fiscal years differ between companies; compare period_start and period_end before "
            "treating rows as the same period.",
            "Only companies this deployment has ingested appear. ambiguous_mapping and "
            "invalid_source_value observations are excluded; values in other units are excluded.",
        ],
    )
