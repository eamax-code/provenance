"""Cross-company screen: one normalized metric for every company, for one year."""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.core.errors import APIError
from app.db.models import Company, FinancialFact
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.public import LatestRevenueCard
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS
from app.services.intel import ANNUAL_FORMS
from app.services.point_in_time import as_of_note, known_by

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
    quarter: int | None = None
    unit: str
    as_of: date | None = None
    data: list[ScreenRow]
    meta: PageMeta
    notes: list[str]


QUARTER_FOUR_NOTE = (
    "Companies with a calendar fiscal year report the October to December quarter only inside "
    "the annual report, so few companies have a reported Q4 value; quarters derived by "
    "subtraction are not used here."
)


def _usable(metric: str, period: str, unit: str):
    return select(FinancialFact).where(
        FinancialFact.metric == metric,
        FinancialFact.period_class == period,
        FinancialFact.unit == unit,
        FinancialFact.derived.is_(False),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.value.is_not(None),
    )


def _rank(f: FinancialFact) -> tuple:
    return (
        f.period_end,
        f.form_type in ANNUAL_FORMS or f.period_class != "annual",
        f.filed_date or date.min,
        f.accession_number or "",
    )


def _month_after(year: int, month: int) -> date:
    return date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)


class QuarterCount(BaseModel):
    quarter: int
    companies: int


class YearCount(BaseModel):
    year: int
    companies: int
    quarters: list[QuarterCount] = []


class ScreenPeriods(BaseModel):
    metric: str
    period: str
    unit: str
    years: list[YearCount]
    notes: list[str]


PERIODS_CACHE_SECONDS = 600
_periods_cache: dict[tuple[str, str, str], tuple[float, ScreenPeriods]] = {}


def reset_periods_cache() -> None:
    _periods_cache.clear()


@router.get(
    "/screen/periods",
    response_model=ScreenPeriods,
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    summary="Years and quarters that have data for a screen",
)
def screen_periods(
    metric: str = Query(..., description=", ".join(SUPPORTED_METRICS)),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    unit: str = Query("USD", max_length=20),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    if metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    key = (metric, period, unit)
    hit = _periods_cache.get(key)
    if hit and time.monotonic() - hit[0] < PERIODS_CACHE_SECONDS:
        return hit[1]
    usable = _usable(metric, period, unit).subquery()
    year = cast(extract("year", usable.c.period_end), Integer)
    month = cast(extract("month", usable.c.period_end), Integer)
    quarter = (month + 2) // 3
    companies = func.count(func.distinct(usable.c.cik))
    by_year = db.execute(select(year, companies).group_by(year)).all()
    by_quarter = (
        db.execute(select(year, quarter, companies).group_by(year, quarter)).all()
        if period == "quarterly"
        else []
    )
    quarters: dict[int, list[QuarterCount]] = {}
    for y, q, n in sorted(by_quarter):
        quarters.setdefault(int(y), []).append(QuarterCount(quarter=int(q), companies=n))
    out = ScreenPeriods(
        metric=metric,
        period=period,
        unit=unit,
        years=[
            YearCount(year=int(y), companies=n, quarters=quarters.get(int(y), []))
            for y, n in sorted(by_year, reverse=True)
        ],
        notes=[
            "Years and quarters are calendar periods of period_end, counted as companies with a "
            "usable value; the same rules as /v1/facts/screen apply.",
            "Counts are refreshed every few minutes.",
        ],
    )
    _periods_cache[key] = (time.monotonic(), out)
    return out


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
    quarter: int | None = Query(
        None,
        ge=1,
        le=4,
        description="Quarterly only: calendar quarter of period_end (1 = Jan to Mar). "
        "Omit for each company's latest quarter in the year.",
    ),
    unit: str = Query("USD", max_length=20),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    as_of: date | None = Query(
        None, description="Point in time: use only observations filed on or before this date"
    ),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    if metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    if quarter is not None and period != "quarterly":
        raise APIError(422, "invalid_parameter", "quarter needs period=quarterly.")
    first_month, last_month = (1, 12) if quarter is None else (3 * quarter - 2, 3 * quarter)
    stmt = _usable(metric, period, unit).where(
        FinancialFact.period_end >= date(year, first_month, 1),
        FinancialFact.period_end < _month_after(year, last_month),
    )
    if as_of:
        stmt = known_by(stmt, as_of)
    rows = db.scalars(stmt).all()
    # Per company: the latest period ending in the year, then the latest-filed observation.
    best: dict[str, FinancialFact] = {}
    for f in rows:
        cur = best.get(f.cik)
        # The latest period; within it the annual report over a proxy statement, then the latest.
        if cur is None or _rank(f) > _rank(cur):
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
    span = "calendar year" if quarter is None else f"calendar quarter Q{quarter}"
    notes = [
        "One row per company: the latest reported period whose period_end falls in the "
        f"requested {span}, using the latest-filed preferred observation.",
        "Fiscal years differ between companies; compare period_start and period_end before "
        "treating rows as the same period.",
        "Only companies this deployment has ingested appear. ambiguous_mapping and "
        "invalid_source_value observations are excluded; values in other units are excluded.",
    ]
    if quarter == 4:
        notes.append(QUARTER_FOUR_NOTE)
    if as_of:
        notes.append(as_of_note(as_of))
    return ScreenResult(
        metric=metric,
        year=year,
        period=period,
        quarter=quarter,
        unit=unit,
        as_of=as_of,
        data=out,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
            total_matched=len(ranked),
        ),
        notes=notes,
    )
