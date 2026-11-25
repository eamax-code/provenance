"""Cross-company screen: one normalized metric for every company, for one year."""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, cast, extract, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, strict_query
from app.core.errors import APIError
from app.db.models import Company, FinancialFact, MartFinancial
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.public import LatestRevenueCard
from app.services import ratios
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS, default_unit
from app.services.intel import ANNUAL_FORMS
from app.services.point_in_time import as_of_note, known_by

router = APIRouter(prefix="/v1/facts", tags=["facts"])


class ScreenRow(LatestRevenueCard):
    cik: str
    legal_name: str
    display_name: str | None = Field(
        default=None, description="The name to show: the overview's rule (cover name, cased)"
    )
    registrant_cik: str | None = Field(
        default=None,
        description="K-05: set when a predecessor registrant filed the figure; the row is listed "
        "under its current successor (cik, names, ticker)",
    )
    predecessor: bool = False
    registrant_label: str | None = None
    ticker: str | None
    exchange: str | None
    metric: str
    mapping_version: str
    derived: bool = False
    derivation: dict | None = Field(
        default=None, description="Derived figures only: formula and the two inputs"
    )


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


def _screen_from_mart(db, metric, year, period, quarter, unit, order, limit, offset, start, stop,
                      only=None):  # fmt: skip
    """The screen from mart_financials: each company's latest period in the window, ranked and
    paged in SQL, so only the rows shown are read."""
    m = MartFinancial
    latest = func.row_number().over(partition_by=m.cik, order_by=m.period_end.desc()).label("rn")
    # Rank and page on the covering index alone; read whole rows only for the page shown.
    inner = (
        select(m.cik, m.period_end, m.value, latest)
        .where(
            m.metric == metric,
            m.period_class == period,
            m.unit == unit,
            m.period_end >= start,
            m.period_end < stop,
            *([only(m.cik)] if only else []),  # D-01
        )
        .subquery()
    )
    picked = select(inner).where(inner.c.rn == 1).subquery()
    total = int(db.scalar(select(func.count()).select_from(picked)) or 0)
    direction = picked.c.value.asc() if order == "asc" else picked.c.value.desc()
    tie = picked.c.cik.asc() if order == "asc" else picked.c.cik.desc()
    page = (
        select(picked.c.cik, picked.c.period_end, picked.c.value)
        .order_by(direction, tie)
        .limit(limit)
        .offset(offset)
        .subquery()
    )
    shown = page.c.value.asc() if order == "asc" else page.c.value.desc()
    rows = db.execute(
        select(m, Company.legal_name, Company.ticker, Company.exchange)
        .join(
            page,
            (m.cik == page.c.cik)
            & (m.period_end == page.c.period_end)
            & (m.metric == metric)
            & (m.period_class == period)
            & (m.unit == unit),
        )
        .join(Company, Company.cik == m.cik)
        .order_by(shown, page.c.cik.asc() if order == "asc" else page.c.cik.desc())
    ).all()
    out = [
        ScreenRow(
            cik=f.cik,
            legal_name=name,
            ticker=ticker,
            exchange=exchange,
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
        for f, name, ticker, exchange in rows
    ]
    out = _present(db, out, None)
    return _result(metric, year, period, quarter, unit, None, out, limit, offset, total)


def _present(db: Session, out: list[ScreenRow], as_of: date | None) -> list[ScreenRow]:
    """display_name on every row (the overview's rule), and K-05 as on the overview: a
    predecessor registrant's figure is listed under its current successor (as of as_of), saying
    which registrant filed it. The successor's own row for the same period wins."""
    from app.db.models import RegistrantSuccession
    from app.services.intel import display_name

    current: dict[str, str] = {}
    frontier = {r.cik for r in out}
    while frontier:  # follow chains (a holdco of a holdco)
        stmt = select(RegistrantSuccession).where(
            RegistrantSuccession.predecessor_cik.in_(frontier)
        )
        if as_of:
            stmt = stmt.where(RegistrantSuccession.effective_date <= as_of)
        step = {s.predecessor_cik: s.successor_cik for s in db.scalars(stmt)}
        for pred, succ in step.items():
            for k, v in list(current.items()):
                if v == pred:
                    current[k] = succ
            current.setdefault(pred, succ)
        frontier = {v for v in step.values() if v not in current}
    ciks = {r.cik for r in out} | set(current.values())
    companies = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(ciks)))}
    own = {(r.cik, r.period_end) for r in out}
    shown = []
    for r in out:
        succ = current.get(r.cik)
        if succ and succ != r.cik and succ in companies:
            if (succ, r.period_end) in own:
                continue  # the successor reported this period itself
            s = companies[succ]
            r.registrant_cik, r.predecessor = r.cik, True
            r.registrant_label = f"Reported by predecessor registrant (CIK {int(r.cik)})"
            r.cik, r.legal_name, r.ticker, r.exchange = s.cik, s.legal_name, s.ticker, s.exchange
        c = companies.get(r.cik)
        if c is not None:
            r.display_name = display_name(c.legal_name, c.ticker, c.registrant_name)
        shown.append(r)
    return shown


def _marts_ready(db: Session) -> bool:
    """Whether mart_financials has been built (scripts/build_marts.py)."""
    return db.scalar(select(MartFinancial.cik).limit(1)) is not None


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
    unit: str | None = Query(
        None,
        max_length=20,
        description="Default: the metric's unit (USD; USD/shares for EPS; shares)",
    ),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    if metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    unit = unit or default_unit(metric)
    key = (metric, period, unit)
    hit = _periods_cache.get(key)
    if hit and time.monotonic() - hit[0] < PERIODS_CACHE_SECONDS:
        return hit[1]
    if _marts_ready(db):
        m = MartFinancial
        usable = (
            select(m.cik, m.period_end)
            .where(m.metric == metric, m.period_class == period, m.unit == unit)
            .subquery()
        )
    else:
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
    dependencies=[Depends(strict_query)],
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
    unit: str | None = Query(
        None,
        max_length=20,
        description="Default: the metric's unit (USD; USD/shares for EPS; shares)",
    ),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    as_of: date | None = Query(
        None, description="Point in time: use only observations filed on or before this date"
    ),
    include_inactive: bool = Query(
        False,
        description="D-01: also companies with no 10-K, 10-Q, 20-F or 40-F of their own "
        "in 18 months (left out by default)",
    ),  # fmt: skip
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    from app.services.marts import periodic_only

    only = None if include_inactive else (lambda col: periodic_only(col, as_of, db))
    ratio = ratios.RATIOS.get(metric)
    if metric not in SUPPORTED_METRICS and ratio is None:
        raise APIError(
            422,
            "invalid_parameter",
            f"metric must be one of: {', '.join(SUPPORTED_METRICS)}, or a derived figure: "
            f"{', '.join(ratios.DERIVED_METRICS)}.",
        )
    unit = unit or (default_unit(metric) if ratio is None else default_unit(ratio.numerator))
    if quarter is not None and period != "quarterly":
        raise APIError(422, "invalid_parameter", "quarter needs period=quarterly.")
    first_month, last_month = (1, 12) if quarter is None else (3 * quarter - 2, 3 * quarter)
    start, stop = date(year, first_month, 1), _month_after(year, last_month)
    if ratio is not None:
        return _screen_derived(
            db,
            metric,
            ratio,
            year,
            period,
            quarter,
            unit,
            order,
            limit,
            offset,
            start,
            stop,
            as_of,
            only,
        )
    if as_of is None and _marts_ready(db):
        return _screen_from_mart(
            db, metric, year, period, quarter, unit, order, limit, offset, start, stop, only
        )
    # Point in time reads every observation, to keep only what was filed by the date.
    stmt = _usable(metric, period, unit).where(
        FinancialFact.period_end >= start, FinancialFact.period_end < stop
    )
    if only:
        stmt = stmt.where(only(FinancialFact.cik))
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
    out = _present(db, out, as_of)
    return _result(metric, year, period, quarter, unit, as_of, out, limit, offset, len(ranked))


def _best(rows: list[FinancialFact]) -> dict[str, FinancialFact]:
    best: dict[str, FinancialFact] = {}
    for f in rows:
        cur = best.get(f.cik)
        if cur is None or _rank(f) > _rank(cur):
            best[f.cik] = f
    return best


def _screen_derived(
    db,
    metric,
    ratio,
    year,
    period,
    quarter,
    unit,
    order,
    limit,
    offset,
    start,
    stop,
    as_of,
    only=None,
):
    """A derived figure (D-03) across companies: each company's latest period in the window,
    paired with the denominator of the same period (or, per share, of the same filing)."""
    num_stmt = _usable(ratio.numerator, period, unit).where(
        FinancialFact.period_end >= start, FinancialFact.period_end < stop
    )
    den_unit = default_unit(ratio.denominator)
    den_stmt = _usable(ratio.denominator, period, den_unit if ratio.kind == "per_share" else unit)
    if ratio.kind != "per_share":  # cover-page shares are dated after the period end
        den_stmt = den_stmt.where(
            FinancialFact.period_end >= start, FinancialFact.period_end < stop
        )
    if as_of:
        num_stmt, den_stmt = known_by(num_stmt, as_of), known_by(den_stmt, as_of)
    if only:
        num_stmt = num_stmt.where(only(FinancialFact.cik))
    best = _best(db.scalars(num_stmt).all())
    if not best:
        return _result(metric, year, period, quarter, ratios.unit_of(ratio, unit), as_of, [],
                       limit, offset, 0)  # fmt: skip
    dens = db.scalars(den_stmt.where(FinancialFact.cik.in_(list(best)))).all()
    paired = []
    for cik, n in best.items():
        mine = [d for d in dens if d.cik == cik]
        for item in ratios.derive(ratio, [n], sorted(mine, key=_rank, reverse=True)):
            paired.append((n, item))
    paired.sort(key=lambda p: (p[1]["value"], p[0].cik), reverse=(order == "desc"))
    page = paired[offset : offset + limit]
    companies = {c.cik: c for c in db.scalars(
        select(Company).where(Company.cik.in_([n.cik for n, _ in page]))
    )} if page else {}  # fmt: skip
    out = []
    for n, item in page:
        c = companies.get(n.cik)
        out.append(ScreenRow(
            cik=n.cik, legal_name=c.legal_name if c else "", ticker=c.ticker if c else None,
            exchange=c.exchange if c else None, metric=metric, value=item["value"],
            unit=item["unit"], currency=None,
            period_start=n.period_start.isoformat() if n.period_start else None,
            period_end=n.period_end.isoformat(), fiscal_year=n.fiscal_year,
            form_type=n.form_type, filed_date=n.filed_date.isoformat() if n.filed_date else None,
            accession_number=n.accession_number, source_tag=ratio.formula,
            source_url=n.source_url, quality_status="derived",
            mapping_version=MAPPING_VERSION, derived=True,
            derivation={"method": ratio.kind, "formula": ratio.formula,
                        "inputs": [ratios.ref(item["numerator"]), ratios.ref(item["denominator"])]},
        ))  # fmt: skip
    out = _present(db, out, as_of)
    return _result(metric, year, period, quarter, ratios.unit_of(ratio, unit), as_of, out, limit,
                   offset, len(paired))  # fmt: skip


def _result(metric, year, period, quarter, unit, as_of, out, limit, offset, total) -> ScreenResult:
    has_more = offset + limit < total
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
    from app.services.marts import INACTIVE_NOTE

    notes.append(INACTIVE_NOTE)
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
            total_matched=total,
        ),
        notes=notes,
    )
