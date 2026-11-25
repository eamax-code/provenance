from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep, strict_query
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import Company, Filing, FinancialFact, utcnow
from app.db.session import session_factory
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.companies import (
    CompanyList,
    CompanyOut,
    CompanyProfile,
    FactList,
    FactOut,
    FilingList,
    FilingOut,
    FirstReportedOut,
    FreshnessOut,
    LegalNameAsFiled,
)
from app.schemas.statements import StatementCell, StatementColumn, StatementOut, StatementRow
from app.services import eps_reconcile, first_reported, periods, ratios
from app.services import freshness as freshness_service
from app.services.company_lookup import search_companies
from app.services.fact_normalizer import (
    MAPPING_VERSION,
    SUPPORTED_METRICS,
    currency_from_unit,
    derive_quarters,
)
from app.services.ingestion import ingest_company
from app.services.point_in_time import as_of_note, known_by
from app.services.quality import is_suspicious_period
from app.services.sec_client import SecClient, SecClientError, normalize_cik

logger = logging.getLogger("app.api.companies")

router = APIRouter(prefix="/v1/companies", tags=["companies"])

_ERRORS = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
}

# On-demand ingestion guard: in-flight CIKs and recent failures (cik -> expiry monotonic time).
_inflight: set[str] = set()
_recent_failures: dict[str, float] = {}
_guard_lock = threading.Lock()
_FAILURE_TTL_SECONDS = 600


def _parse_cik_param(cik: str) -> str:
    try:
        return normalize_cik(cik)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be 1-10 digits.") from exc


def get_sec_client_factory(request: Request):
    """Returns a zero-arg callable creating a SecClient; overridable in tests."""
    factory = getattr(request.app.state, "sec_client_factory", None)
    if factory is None:
        settings = request.app.state.settings

        def factory():
            return SecClient(settings)

    return factory


def _run_on_demand_ingestion(cik: str, client_factory) -> None:
    db = session_factory()()
    client = None
    try:
        client = client_factory()
        ingest_company(db, client, cik)
    except SecClientError as exc:
        logger.info(
            "on-demand ingestion failed",
            extra={"extra_fields": {"cik": cik, "error": type(exc).__name__}},
        )
        with _guard_lock:
            _recent_failures[cik] = time.monotonic() + _FAILURE_TTL_SECONDS
    except Exception:  # noqa: BLE001
        logger.exception("on-demand ingestion crashed", extra={"extra_fields": {"cik": cik}})
        with _guard_lock:
            _recent_failures[cik] = time.monotonic() + _FAILURE_TTL_SECONDS
    finally:
        db.close()
        if client is not None:
            client.close()
        with _guard_lock:
            _inflight.discard(cik)


def _schedule_ingestion(cik: str, background: BackgroundTasks, request: Request) -> bool:
    with _guard_lock:
        expiry = _recent_failures.get(cik)
        if expiry and expiry > time.monotonic():
            return False
        _recent_failures.pop(cik, None)
        if cik in _inflight:
            return True
        _inflight.add(cik)
    background.add_task(_run_on_demand_ingestion, cik, get_sec_client_factory(request))
    return True


def _company_out(
    c: Company, match_type: str | None = None, matched_name: str | None = None
) -> CompanyOut:
    from app.services.intel import display_name

    out = CompanyOut.model_validate(c)
    out.display_name = display_name(c.legal_name, c.ticker, c.registrant_name)
    out.match_type = match_type
    out.matched_name = matched_name
    if c.last_processed_at is None:
        out.ingestion_status = "failed" if c.last_fetch_error else "pending"
    return out


@router.get(
    "",
    response_model=CompanyList,
    responses=_ERRORS,
    summary="List companies with filters (paginated)",
)
def list_companies(
    exchange: str | None = Query(None, max_length=20, description="e.g. Nasdaq, NYSE"),
    sic: str | None = Query(None, max_length=4, description="SEC SIC code"),
    state: str | None = Query(None, max_length=2, description="State of incorporation"),
    ingested: bool | None = Query(None, description="Only companies with filings ingested"),
    sort: str = Query("name", pattern="^(name|cik|last_processed)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    stmt = select(Company)
    if exchange:
        stmt = stmt.where(func.upper(Company.exchange) == exchange.upper())
    if sic:
        stmt = stmt.where(Company.sic_code == sic)
    if state:
        stmt = stmt.where(func.upper(Company.state_of_incorporation) == state.upper())
    if ingested is True:
        stmt = stmt.where(Company.last_processed_at.is_not(None))
    elif ingested is False:
        stmt = stmt.where(Company.last_processed_at.is_(None))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    order = {
        "name": (Company.legal_name, Company.cik),
        "cik": (Company.cik,),
        "last_processed": (Company.last_processed_at.desc().nulls_last(), Company.cik),
    }[sort]
    rows = db.scalars(stmt.order_by(*order).offset(offset).limit(limit)).all()
    has_more = offset + len(rows) < total
    return CompanyList(
        data=[_company_out(c) for c in rows],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
            total_matched=total,
        ),
    )


@router.get(
    "/search",
    response_model=CompanyList,
    responses=_ERRORS,
    summary="Find companies by ticker, CIK, name or former name",
)
def search(
    q: str = Query(min_length=1, max_length=100, description="Ticker, CIK, or company name"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    hits, has_more = search_companies(db, q, limit)
    return CompanyList(
        data=[_company_out(h.company, h.match_type, h.former_name) for h in hits],
        meta=PageMeta(limit=limit, has_more=has_more),
    )


@router.get(
    "/{cik}",
    response_model=CompanyProfile,
    responses={**_ERRORS, 202: {"model": CompanyProfile, "description": "Ingestion in progress"}},
    summary="One company: identity, tickers, addresses and filer details",
)
def profile(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    company = db.scalar(select(Company).where(Company.cik == cik))
    demo = getattr(request.state, "demo", False)
    if company is None:
        if (
            not demo
            and settings.on_demand_ingestion_enabled
            and _schedule_ingestion(cik, background, request)
        ):
            response.status_code = 202
            response.headers["Retry-After"] = "10"
            return CompanyProfile(
                cik=cik,
                legal_name="",
                ticker=None,
                exchange=None,
                last_processed_at=None,
                quality_status="unavailable",
                ingestion_status="processing",
            )
        raise APIError(404, "company_not_found", "No company with this CIK is available.")

    out = CompanyProfile.model_validate(company)
    from app.services.intel import display_name
    from app.services.ticker_history import legal_name_as_filed

    out.display_name = display_name(company.legal_name, company.ticker, company.registrant_name)

    filed = legal_name_as_filed(company)
    out.legal_name_as_filed = LegalNameAsFiled(**filed) if filed else None
    out.filings_count = int(db.scalar(select(func.count(Filing.id)).where(Filing.cik == cik)) or 0)
    out.facts_count = int(
        db.scalar(select(func.count(FinancialFact.id)).where(FinancialFact.cik == cik)) or 0
    )
    if company.last_processed_at is None:
        scheduled = (
            (not demo)
            and settings.on_demand_ingestion_enabled
            and _schedule_ingestion(cik, background, request)
        )
        out.ingestion_status = (
            "processing" if scheduled else ("failed" if company.last_fetch_error else "pending")
        )
        if scheduled:
            response.status_code = 202
            response.headers["Retry-After"] = "10"
    return out


@router.get(
    "/{cik}/filings",
    response_model=FilingList,
    responses=_ERRORS,
    summary="A company's SEC filings, newest first, with links",
)
def filings(
    cik: str = Path(max_length=13),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    form_type: str | None = Query(None, max_length=20),
    since: date | None = Query(None, description="Only filings with filing_date >= since"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    stmt = select(Filing).where(Filing.cik == cik)
    if form_type:
        stmt = stmt.where(func.upper(Filing.form_type) == form_type.upper())
    if since:
        stmt = stmt.where(Filing.filing_date >= since)
    stmt = (
        stmt.order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = db.scalars(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return FilingList(
        data=[FilingOut.model_validate(r) for r in rows],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )


@router.get(
    "/{cik}/facts",
    dependencies=[Depends(strict_query)],
    response_model=FactList,
    responses=_ERRORS,
    summary="Reported financial figures, each with its filing; as_of for point in time",
)
def facts(
    cik: str = Path(max_length=13),
    metric: str | None = Query(
        None,
        description=f"One of {', '.join(SUPPORTED_METRICS)}, or a derived figure: "
        f"{', '.join(ratios.DERIVED_METRICS)}",
    ),
    period: str = Query("annual", pattern="^(annual|quarterly|all)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    from_: date | None = Query(None, alias="from", description="period_end >= from"),
    to: date | None = Query(None, description="period_end <= to"),
    form_type: str | None = Query(None, max_length=20),
    include_derived: bool = Query(
        False, description="Include quarter values derived by subtraction"
    ),
    include_all_observations: bool = Query(
        False,
        description="Return every stored observation (restatements, alternate tags) instead of "
        "the latest-filed preferred observation per period",
    ),
    as_of: date | None = Query(
        None,
        description="Point in time: use only observations filed with the SEC on or before this "
        "date, so restatements filed later are not visible",
    ),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    ratio = ratios.RATIOS.get(metric or "")
    if metric is not None and metric not in SUPPORTED_METRICS and ratio is None:
        raise APIError(
            422,
            "invalid_parameter",
            f"metric must be one of: {', '.join(SUPPORTED_METRICS)}, or a derived figure: "
            f"{', '.join(ratios.DERIVED_METRICS)}.",
        )
    stmt = select(FinancialFact).where(FinancialFact.cik == cik, FinancialFact.derived.is_(False))
    if ratio is not None:
        stmt = stmt.where(FinancialFact.metric.in_([ratio.numerator, ratio.denominator]))
    elif metric:
        stmt = stmt.where(FinancialFact.metric == metric)
    if from_:
        stmt = stmt.where(FinancialFact.period_end >= from_)
    if to:
        stmt = stmt.where(FinancialFact.period_end <= to)
    if form_type:
        stmt = stmt.where(func.upper(FinancialFact.form_type) == form_type.upper())
    if period != "all":
        stmt = stmt.where(FinancialFact.period_class == period)
    if as_of:
        stmt = known_by(stmt, as_of)
    rows = db.scalars(stmt).all()
    if ratio is not None:
        return _derived_page(cik, company, metric, ratio, rows, limit, offset, as_of)

    notes = [
        "Values are as reported by the issuer to the SEC; period_class is derived from the "
        "reported duration, not from the SEC fiscal-period label.",
    ]
    selected = (
        _select_latest(rows)
        if not include_all_observations
        else [_to_fact_out(r, 1, True) for r in rows]
    )
    if not include_all_observations:
        notes.append(
            "One observation per metric/unit/period is returned (latest filed, preferred tag). "
            "Set include_all_observations=true to see restatements and alternate tags."
        )

    if include_derived and period in ("quarterly", "all"):
        from app.services.fact_normalizer import NormalizedFact

        base_stmt = select(FinancialFact).where(
            FinancialFact.cik == cik,
            FinancialFact.derived.is_(False),
            FinancialFact.period_type == "duration",
        )
        if metric:
            base_stmt = base_stmt.where(FinancialFact.metric == metric)
        if as_of:
            base_stmt = known_by(base_stmt, as_of)
        source_rows = db.scalars(base_stmt).all()
        nfs = [_row_to_normalized(r) for r in source_rows]
        derived = derive_quarters([n for n in nfs if isinstance(n, NormalizedFact)])
        for d in derived:
            if from_ and d.period_end < from_:
                continue
            if to and d.period_end > to:
                continue
            if form_type and (d.form_type or "").upper() != form_type.upper():
                continue
            selected.append(_derived_out(cik, d, source_rows))
        notes.append(
            "Derived quarter values (derived=true) are computed by this service by subtracting "
            "two reported year-to-date observations; they are not reported by the issuer."
        )
    if as_of:
        notes.append(as_of_note(as_of))

    selected.sort(
        key=lambda f: (f.period_end, f.period_start or date.min, f.metric, f.source_tag),
        reverse=True,
    )
    total = len(selected)
    page = selected[offset : offset + limit]
    stated = first_reported.lookup(db, cik, {f.accession_number for f in page
                                             if f.accession_number and not f.derived})  # fmt: skip
    for f in page:
        hit = stated.get((f.accession_number, f.metric, f.unit, f.period_start, f.period_end))
        if hit is not None and not f.derived:
            f.first_reported = FirstReportedOut(**first_reported.as_dict(hit))
    if stated:
        notes.append(first_reported.NOTE)
    for f in page:  # the period's own fiscal year, whatever filing reported it
        f.period_fiscal_year = periods.fiscal_year(f.period_end, periods.convention(company),
                                                     period_class=f.period_class)
        f.calendar_period = periods.calendar_period(f.period_start, f.period_end, f.period_class)
        if f.period_class in ("annual", "quarterly"):
            f.period_label = periods.label(f.period_end, f.period_class,
                                           periods.convention(company))
    has_more = offset + limit < total
    return FactList(
        data=page,
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
            total_matched=total,
        ),
        mapping_version=MAPPING_VERSION,
        as_of=as_of,
        notes=notes,
    )


@router.get(
    "/{cik}/freshness",
    response_model=FreshnessOut,
    responses=_ERRORS,
    summary="How fresh a company's data is: last fetch, latest filing, status",
)
def freshness(
    cik: str = Path(max_length=13),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    return freshness_service.company_freshness(db, company, settings)


# --- helpers --------------------------------------------------------------------------------


def _require_company(db: Session, cik: str) -> Company:
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        raise APIError(404, "company_not_found", "No company with this CIK is available.")
    return company


def _to_fact_out(row: FinancialFact, revision_count: int, is_latest: bool) -> FactOut:
    out = FactOut.model_validate(row)
    if is_suspicious_period(row.period_end, row.filed_date):
        out.quality_status = "suspicious_period"  # before 1993, or 2+ years after its filing
    out.derivation = json.loads(row.derivation) if row.derivation else None
    out.revision_count = revision_count
    out.is_latest_revision = is_latest
    return out


def _select_latest(rows: list[FinancialFact]) -> list[FactOut]:
    """Pick, per (metric, unit, period), the latest-filed observation of the preferred tag."""
    groups: dict[tuple, list[FinancialFact]] = {}
    for r in rows:
        groups.setdefault((r.metric, r.unit, r.period_start, r.period_end), []).append(r)
    out: list[FactOut] = []
    for items in groups.values():
        preferred = [r for r in items if r.quality_status in ("ok", "partial")] or items
        # M-01: the observation key breaks ties, so two runs (and the marts) pick the same row
        best = max(preferred, key=lambda r: (r.filed_date or date.min, r.accession_number or "",
                                             r.observation_key or ""))
        same_tag = [r for r in items if r.source_tag == best.source_tag]
        out.append(_to_fact_out(best, len(same_tag), True))
    return out


def _row_to_normalized(r: FinancialFact):
    from app.services.fact_normalizer import NormalizedFact

    return NormalizedFact(
        metric=r.metric,
        value=r.value,
        unit=r.unit,
        currency=r.currency,
        period_start=r.period_start,
        period_end=r.period_end,
        period_type=r.period_type,
        period_class=r.period_class,
        fiscal_year=r.fiscal_year,
        fiscal_period=r.fiscal_period,
        form_type=r.form_type,
        filed_date=r.filed_date,
        accession_number=r.accession_number,
        source_tag=r.source_tag,
        source_taxonomy=r.source_taxonomy,
        source_url=r.source_url,
        mapping_version=r.mapping_version,
        quality_status=r.quality_status,
        derived=r.derived,
    )


def _derived_page(cik, company, metric, ratio, rows, limit, offset, as_of) -> FactList:
    """A derived figure (D-03) per period from the latest preferred observations of its inputs."""
    base = _select_latest([r for r in rows if r.quality_status in ("ok", "partial")])
    nums = [f for f in base if f.metric == ratio.numerator]
    dens = [f for f in base if f.metric == ratio.denominator]
    out = []
    for item in ratios.derive(ratio, nums, dens):
        n, d = item["numerator"], item["denominator"]
        out.append(
            FactOut(
                cik=cik, metric=metric, value=item["value"], unit=item["unit"],
                currency=None if item["unit"] in ("%", "x") else currency_from_unit(item["unit"]),
                period_start=n.period_start, period_end=n.period_end, period_type=n.period_type,
                period_class=n.period_class, fiscal_year=n.fiscal_year,
                fiscal_period=n.fiscal_period, form_type=n.form_type, filed_date=n.filed_date,
                accession_number=n.accession_number, source_tag=ratio.formula,
                source_taxonomy="derived", source_url=n.source_url,
                mapping_version=MAPPING_VERSION, quality_status="derived", derived=True,
                derivation={"method": ratio.kind, "formula": ratio.formula,
                            "inputs": [ratios.ref(n), ratios.ref(d)]},
                revision_count=1, is_latest_revision=True, processed_at=n.processed_at,
            )
        )  # fmt: skip
    out.sort(key=lambda f: f.period_end, reverse=True)
    for f in out:
        f.period_fiscal_year = periods.fiscal_year(f.period_end, periods.convention(company),
                                                     period_class=f.period_class)
        f.calendar_period = periods.calendar_period(f.period_start, f.period_end, f.period_class)
        if f.period_class in ("annual", "quarterly"):
            f.period_label = periods.label(f.period_end, f.period_class,
                                           periods.convention(company))
    page = out[offset : offset + limit]
    has_more = offset + limit < len(out)
    notes = [
        f"{ratio.label} is derived by this service ({ratio.formula}) from two reported "
        "figures of the same period; each row lists its inputs and their filings.",
    ]
    if as_of:
        notes.append(as_of_note(as_of))
    return FactList(
        data=page,
        meta=PageMeta(limit=limit, offset=offset, has_more=has_more,
                      next_offset=offset + limit if has_more else None, total_matched=len(out)),
        mapping_version=MAPPING_VERSION, as_of=as_of, notes=notes,
    )  # fmt: skip


def _derived_out(cik: str, d, source_rows: list[FinancialFact]) -> FactOut:
    now_rows = [r for r in source_rows if r.accession_number == d.accession_number]
    processed = max((r.processed_at for r in now_rows), default=None)
    return FactOut(
        cik=cik,
        metric=d.metric,
        value=d.value,
        unit=d.unit,
        currency=d.currency,
        period_start=d.period_start,
        period_end=d.period_end,
        period_type=d.period_type,
        period_class=d.period_class,
        fiscal_year=d.fiscal_year,
        fiscal_period=d.fiscal_period,
        form_type=d.form_type,
        filed_date=d.filed_date,
        accession_number=d.accession_number,
        source_tag=d.source_tag,
        source_taxonomy=d.source_taxonomy,
        source_url=d.source_url,
        mapping_version=d.mapping_version,
        quality_status="derived",
        derived=True,
        derivation=d.derivation,
        revision_count=1,
        is_latest_revision=True,
        processed_at=processed or utcnow(),
    )


# X-02 (docs/api-contracts-explorer.md): a whole statement in one call. Each cell is the value
# /facts returns by default for that metric and period (_select_latest); derived rows use the
# ratio definitions /facts uses for derived figures.
STATEMENT_ROWS = {
    "income": ("revenue", "cost_of_revenue", "gross_profit", "r_and_d", "sga", "operating_income",
               "interest_expense", "net_interest_income", "pretax_income", "income_tax",
               "net_income", "profit_loss", "eps_basic", "eps_diluted", "shares_basic_weighted",
               "shares_diluted_weighted"),
    "balance": ("cash_and_equivalents", "current_assets", "total_assets", "current_liabilities",
                "long_term_debt_current", "long_term_debt", "total_liabilities",
                "stockholders_equity", "retained_earnings", "shares_outstanding"),
    "cash_flow": ("operating_cash_flow", "capex", "d_and_a", "sbc", "dividends_paid",
                  "share_repurchases"),
}  # fmt: skip
STATEMENT_DERIVED = {
    "income": ("gross_margin", "operating_margin", "net_margin"),
    "balance": ("current_ratio", "debt_to_equity"),
    "cash_flow": ("free_cash_flow",),
}
STATEMENT_PERIODS = {"annual": (12, 20), "quarterly": (40, 80)}  # (default, max) columns
COVER_METRICS = {"shares_outstanding"}  # dated at the cover page, after the period


@router.get(
    "/{cik}/statements/{statement}",
    response_model=StatementOut,
    responses=_ERRORS,
    summary="A whole income statement, balance sheet or cash flow statement, 10+ years, each "
    "value with its filing",
)
def statement(
    cik: str = Path(max_length=13),
    statement: str = Path(pattern="^(income|balance|cash_flow)$"),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    periods_: int | None = Query(
        None, alias="periods", ge=1, le=80, description="Columns: up to 20 annual, 80 quarterly"
    ),  # fmt: skip
    as_of: date | None = Query(None, description="Only figures filed by this date"),
    include_derived: bool = Query(
        True,
        description="Derived quarters (Q4 = FY - 9M) and "
        "derived rows (margins, free cash flow, ...)",
    ),  # fmt: skip
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    from app.db.models import MartCompany
    from app.services.fact_normalizer import METRIC_LABELS, METRIC_UNIT_KIND, NormalizedFact

    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    default, most = STATEMENT_PERIODS[period]
    if periods_ is not None and periods_ > most:
        raise APIError(422, "invalid_parameter", f"periods is at most {most} for {period}.")
    n_cols = periods_ or default
    metrics = STATEMENT_ROWS[statement]
    from app.services import statements as statements_service
    from app.services import successions

    # K-05: a successor's statement continues with its predecessors' figures, as the overview
    ciks = [cik] + [p.predecessor_cik for p in successions.predecessors(db, cik)]
    stmt = select(FinancialFact).where(
        FinancialFact.cik.in_(ciks), FinancialFact.derived.is_(False),
        FinancialFact.metric.in_(metrics), FinancialFact.period_class == period,
    )  # fmt: skip
    if as_of:
        stmt = known_by(stmt, as_of)
    chosen = _select_latest(db.scalars(stmt).all())
    if include_derived and period == "quarterly":
        base = select(FinancialFact).where(
            FinancialFact.cik.in_(ciks), FinancialFact.derived.is_(False),
            FinancialFact.period_type == "duration", FinancialFact.metric.in_(metrics),
        )  # fmt: skip
        if as_of:
            base = known_by(base, as_of)
        source_rows = db.scalars(base).all()
        nfs = [_row_to_normalized(r) for r in source_rows]
        have = {(f.metric, f.period_end) for f in chosen}
        for d in derive_quarters([n for n in nfs if isinstance(n, NormalizedFact)]):
            if (d.metric, d.period_end) not in have:
                chosen.append(_derived_out(cik, d, source_rows))
    mart = db.get(MartCompany, cik)
    currency = mart.reporting_currency if mart else None
    # one cell per metric and period: the reporting currency first when a metric has several
    by_key: dict[tuple, FactOut] = {}
    # the company's own filing first, then the reporting currency
    for f in sorted(chosen, key=lambda f: (f.cik != cik, f.unit != currency, f.unit)):
        by_key.setdefault((f.metric, f.period_end), f)
    if not by_key:
        raise APIError(404, "no_statement_data", "No figures of this statement are loaded.")
    # a cover-page figure (shares outstanding) is dated at the cover, after the period: it joins
    # the latest column ending on or before that date, never a column of its own
    cover = {k: v for k, v in by_key.items() if k[0] in COVER_METRICS}
    for k in cover:
        by_key.pop(k)
    transitions: dict = {}  # S-07: end -> start of a year-end changer's transition period
    span_form: dict = {}
    if period == "annual":
        # S-07: annual columns are the company's own fiscal years (and its predecessors'), the
        # year each annual report covers; other 12-month periods in a 10-K are never columns
        own = set()
        for c in db.scalars(select(Company).where(Company.cik.in_(ciks))):
            own.update(periods.parse_year_ends(c.fiscal_year_ends))
        own_ends = tuple(sorted(own))
        # a year-end changer's transition period (10-KT, or a 20-F or 10-K transition report)
        from app.services import fiscal_years

        found = [x for xs in fiscal_years.transitions(db, ciks, as_of).values() for x in xs]
        t_ends = {x[1] for x in found}  # a balance at a transition's end is a period end too
        for k in [k for k in by_key if not periods.is_fiscal_year_end(k[1], own_ends)
                  and not any(abs((k[1] - t).days) <= 7 for t in t_ends)]:  # fmt: skip
            by_key.pop(k)
        # S-07b: one column per fiscal year end; an adoption-date balance (January 1, 2018)
        # beside the year end stays in /facts
        counts: dict = {}
        for _, e in by_key:
            counts[e] = counts.get(e, 0) + 1
        reports = set(db.scalars(select(Filing.report_date).where(
            Filing.cik.in_(ciks), Filing.form_type.in_(fiscal_years.FORMS),
            Filing.report_date.is_not(None))))  # fmt: skip
        skip = {e for e in counts if any(abs((e - t).days) <= 7 for t in t_ends)}
        drop = periods.one_per_year_end(counts, own_ends, reports, skip)
        # a figure the year has at no other date (Superior's 2015 revenue at December 31 beside
        # its balance sheet at December 27) is kept in the year's column, with its own date
        for k in sorted((k for k in by_key if k[1] in drop),
                        key=lambda k: abs((k[1] - drop[k[1]]).days)):  # fmt: skip
            f = by_key.pop(k)
            by_key.setdefault((k[0], drop[k[1]]), f)
        spans = {(x[0], x[1]): x[2] for x in found}
        span_form = {x[1]: x[3] for x in found}  # the cover's form: 10-KT, or 10-K or 20-F
        if spans:
            tq = select(FinancialFact).where(
                FinancialFact.cik.in_(ciks), FinancialFact.derived.is_(False),
                FinancialFact.metric.in_(metrics),
                FinancialFact.accession_number.in_(set(spans.values())))  # fmt: skip
            if as_of:
                tq = known_by(tq, as_of)
            trows = [r for r in db.scalars(tq) if (r.period_start, r.period_end) in spans]
            for f in _select_latest(trows):
                if (f.metric, f.period_end) not in by_key:
                    by_key[(f.metric, f.period_end)] = f
                    transitions[f.period_end] = f.period_start
    quarter_in: dict = {}  # S-07: a quarter ending inside a transition period -> (label, form)
    if period == "quarterly":
        from app.services import fiscal_years

        spans_q = sorted({(x[0], x[1], x[3]) for xs in fiscal_years.transitions(
            db, ciks, as_of).values() for x in xs})  # fmt: skip
        # its quarters run in sequence from its first day, each starting the day after the last
        # ended; any other quarter inside it is a later report's recast calendar quarter
        # (Pandora's quarters to March, June and September 2013 beside its transition's to
        # April, July and October) and keeps its own label
        qs = sorted({(f.period_start, e) for (_, e), f in by_key.items() if f.period_start})
        week = timedelta(days=7)
        for t0, t1, form in spans_q:
            cur, n = t0, 0
            while True:
                nxt = [e for s, e in qs if abs((s - cur).days) <= week.days
                       and max(t0, cur) < e <= t1 + week]  # fmt: skip
                if not nxt:
                    break
                n, end = n + 1, min(nxt)
                quarter_in[end] = (f"Transition Q{n} (ended {end.isoformat()})", form)
                cur = end + timedelta(days=1)
    ends = sorted({end for _, end in by_key})[-n_cols:]
    for (m, dated), f in sorted(cover.items(), key=lambda kv: kv[0][1]):
        home = [e for e in ends if e <= dated and (dated - e).days <= 120]
        if home:
            by_key[(m, home[-1])] = f  # the latest cover date for a column wins
    if not ends and cover:
        raise APIError(404, "no_statement_data", "No figures of this statement are loaded.")
    starts = {}
    for (_, end), f in by_key.items():
        if f.period_start and end in ends:
            starts.setdefault(end, f.period_start)
    columns = []
    conv = periods.convention(company)  # S-05, S-07: the company's own naming
    fiscal = [e for e in ends if e not in transitions and e not in quarter_in]
    names = dict(zip(fiscal, periods.labels(fiscal, period, conv), strict=True))
    for end in ends:
        if end in quarter_in:  # S-07: a quarter inside a transition period, never Qn FYyyyy
            label, form = quarter_in[end]
            columns.append(StatementColumn(
                key=label, period_label=label, period_fiscal_year=None,
                period_start=starts.get(end), period_end=end, calendar_period=None,
                transition=True, transition_form=form,
            ))  # fmt: skip
            continue
        if end in transitions:  # S-07: never a fiscal year, never in year-on-year comparisons
            label = periods.transition_label(transitions[end], end)
            columns.append(StatementColumn(
                key=label, period_label=label, period_fiscal_year=None,
                period_start=transitions[end], period_end=end, calendar_period=None,
                transition=True, transition_form=span_form.get(end),
            ))  # fmt: skip
            continue
        label = names[end]
        columns.append(StatementColumn(
            key=label, period_label=label,
            period_fiscal_year=periods.fiscal_year(end, conv, period_class=period),
            period_start=starts.get(end), period_end=end,
            calendar_period=periods.calendar_period(starts.get(end), end, period),
        ))  # fmt: skip
    keys = {c.period_end: c.key for c in columns}
    # S-06: EPS that does not reconcile with the same filing's net income over weighted shares:
    # shown as filed, with a note on it and on the shares cell it was checked against
    recon: dict = {}
    off_by_period: dict = {}  # S-06b: (metric, start, end) -> flagged figures, latest first
    flagged_ciks = sorted({f.cik for f in by_key.values()})
    if flagged_ciks and db.scalar(select(FinancialFact.id).where(
            FinancialFact.cik.in_(flagged_ciks),
            FinancialFact.quality_status.in_(eps_reconcile.STATUSES)).limit(1)):  # fmt: skip
        for x in eps_reconcile.find(db, flagged_ciks):
            n = eps_reconcile.NOTE
            recon[(x["accession_number"], x["metric"], x["period_end"])] = n
            recon[(x["accession_number"], eps_reconcile.PAIRS[x["metric"]], x["period_end"])] = n
        for x in eps_reconcile.find_off(db, flagged_ciks):
            if as_of is None or x["filed_date"] is None or x["filed_date"] <= as_of:
                off_by_period.setdefault((x["metric"], x["period_start"], x["period_end"]),
                                         []).append(x)  # fmt: skip

    def s06b(f: FactOut) -> tuple[bool, str | None]:
        """(blank, note): the cell shows another filing's agreeing figure in place of a later
        one off by a scale; or the figure shown is itself off and none agreeing was filed by the
        date asked, and the cell is blank (no look-ahead)."""
        for x in off_by_period.get((f.metric, f.period_start, f.period_end), []):
            if x["accession_number"] == f.accession_number:
                return True, eps_reconcile.scale_note(x)
        later = [x for x in off_by_period.get((f.metric, f.period_start, f.period_end), [])
                 if f.filed_date is None or (x["filed_date"] and x["filed_date"] >= f.filed_date)]
        if later:
            x = max(later, key=lambda x: x["filed_date"])
            return False, eps_reconcile.scale_note(
                x, {"form": f.form_type, "filed_date": f.filed_date})
        return False, None

    # M-01: a filing reporting two figures for one period (IFRS beside US GAAP) that the
    # company's other filings back neither of: no figure is shown, with a note
    m01: set = set()
    if any(f.quality_status == "ambiguous_mapping" for f in by_key.values()):
        from app.services import filing_conflicts

        m01 = {(c["accession_number"], c["metric"], c["period_start"], c["period_end"])
               for c in filing_conflicts.find(db, flagged_ciks, filing_conflicts.STATUSES)
               if c["none"]}  # fmt: skip

    def cell(f: FactOut, end) -> StatementCell:
        own = statements_service.registrant(f, cik)
        blank, scale = s06b(f)
        if f.quality_status == "ambiguous_mapping" and (
                f.accession_number, f.metric, f.period_start, f.period_end) in m01:  # fmt: skip
            from app.services.filing_conflicts import NOTE as M01

            blank, scale = True, M01
        return StatementCell(
            column=keys[end],
            value=None if blank or f.value is None else float(f.value),
            unit=f.unit, period_start=f.period_start,
            period_end=f.period_end, form_type=f.form_type, filed_date=f.filed_date,
            accession_number=f.accession_number, source_url=f.source_url, source_tag=f.source_tag,
            source_taxonomy=f.source_taxonomy, mapping_version=f.mapping_version,
            quality_status=f.quality_status, derived=f.derived, derivation=f.derivation,
            registrant_cik=own["registrant_cik"], predecessor=own["predecessor"],
            registrant_label=own.get("registrant_label"),
            quality_note=scale or recon.get((f.accession_number, f.metric, f.period_end)),
        )  # fmt: skip

    rows = []
    for m in metrics:
        cells = [cell(by_key[(m, end)], end) if (m, end) in by_key else None for end in ends]
        if any(cells):
            rows.append(StatementRow(metric=m, label=METRIC_LABELS[m],
                                     unit_kind=METRIC_UNIT_KIND[m], cells=cells))  # fmt: skip
    if include_derived:
        for name in STATEMENT_DERIVED[statement]:
            r = ratios.RATIOS[name]
            cells = []
            for end in ends:
                num, den = by_key.get((r.numerator, end)), by_key.get((r.denominator, end))
                value = None
                both = num is not None and den is not None and not any(
                    x.quality_status in eps_reconcile.STATUSES for x in (num, den))  # S-06
                if both and ratios.compatible(r, num.unit, den.unit):
                    value = ratios.compute(r, float(num.value), float(den.value))
                if value is None:
                    cells.append(None)
                    continue
                cells.append(StatementCell(
                    column=keys[end], value=value, unit=ratios.unit_of(r, num.unit),
                    period_start=num.period_start, period_end=end, derived=True,
                    mapping_version=num.mapping_version,
                    inputs=[{"metric": x.metric, "accession_number": x.accession_number,
                             "source_url": x.source_url} for x in (num, den)],
                ))  # fmt: skip
            if any(cells):
                rows.append(StatementRow(metric=name, label=r.label, unit_kind=r.kind,
                                         derived=True, formula=r.formula, cells=cells))  # fmt: skip
    notes = ["Values are as reported in each filing, in the company's reporting currency; "
             "nothing is converted. Derived rows and quarters say derived and list their "
             "inputs."]  # fmt: skip

    reviewed = statements_service.reviewed_splits()
    labels = [c.key for c in columns]
    share_eps = statements_service.SHARE_ROWS + statements_service.EPS_ROWS

    def filing_at(label: str) -> dict | None:
        """The filing behind a column of the share and EPS rows (for the first column on the
        newer basis: the filing that restated that year)."""
        k = labels.index(label)
        for r in rows:
            c = r.cells[k] if not r.derived and r.metric in share_eps else None
            if c is not None and c.accession_number:
                filed = c.filed_date.isoformat() if c.filed_date else None
                return {"accession_number": c.accession_number, "form": c.form_type,
                        "filed_date": filed, "source_url": c.source_url}  # fmt: skip
        return None

    def reviewed_match(between: list[str], hint: str) -> tuple[bool, str | None]:
        """S-02b/c: a reviewed split confirms the pair when its effective date falls after the
        older column's filing and by the filing that restated the newer one (a company with two
        splits of one ratio, Amphenol 2021 and 2024, gets each its own). One undated row for the
        ratio confirms on its own."""
        dates = reviewed.get((cik, hint)) if isinstance(reviewed, dict) else None
        if dates is None:
            return ((cik, hint) in reviewed, None) if isinstance(reviewed, set) else (False, None)
        dates = [dates] if isinstance(dates, str) else list(dates)
        a, b_ = filing_at(between[0]), filing_at(between[1])
        lo = date.fromisoformat(a["filed_date"]) if a and a["filed_date"] else None
        hi = date.fromisoformat(b_["filed_date"]) if b_ and b_["filed_date"] else None
        for d in dates:
            if not d:
                continue
            first, last = statements_service.date_span(d)
            if (lo is None or last > lo) and (hi is None or first <= hi):
                return True, d
        return (len(dates) == 1 and not dates[0]), None

    def restated(between: list[str], hint: str) -> bool:  # S-02b: a reviewed split
        return reviewed_match(between, hint)[0]

    def placed() -> list[tuple[int, str]]:
        """S-02c: each reviewed split of this company at the pair of columns whose filings
        bracket its date (after the older column's filing, by the newer one's)."""
        if not isinstance(reviewed, dict):
            return []
        filed = []
        for lab in labels:
            f = filing_at(lab)
            filed.append(date.fromisoformat(f["filed_date"]) if f and f["filed_date"] else None)
        out = []
        for (c_, hint), dates in reviewed.items():
            if c_ != cik:
                continue
            for d in [dates] if isinstance(dates, str) else dates:
                if not d:
                    continue
                first, last = statements_service.date_span(d)
                at = [i for i in range(1, len(labels)) if filed[i - 1] and filed[i]
                      and last > filed[i - 1] and first <= filed[i]]  # fmt: skip
                if len(at) == 1:  # columns filed out of order (an S-1 re-presenting old
                    out.append((at[0], hint))  # years) can bracket a date twice: then none
        return out

    # a reviewed split with a date: each share and EPS cell's basis from its own filing's date
    # (quarterly too: a 10-Q restates only the quarters it shows again)
    dated = statements_service.dated_splits().get(cik, [])
    bases, counted = statements_service.cell_bases(
        {r.metric: r.cells for r in rows if not r.derived and r.metric in share_eps}, dated
    )
    if dated:  # the dates decide: one basis throughout is no break
        breaks = statements_service.basis_breaks(bases, labels, counted) if bases else {}
    else:  # a reviewed split without a date (one row): the share-row guard places it
        accs = [(filing_at(lab) or {}).get("accession_number") for lab in labels]
        one_filing = {i for i in range(1, len(labels)) if accs[i] and accs[i] == accs[i - 1]}
        breaks = statements_service.split_breaks(
            {r.metric: [c.value if c else None for c in r.cells] for r in rows if not r.derived},
            labels,
            restated,
            placed(),
            one_filing,
            reviewed_only=True,
        )
    if breaks:

        def month(d: str) -> str:
            return statements_service.date_label(d)

        def note(b: dict) -> tuple:
            """A row's split note, built from that row's own break (rows can differ: EPS cited
            from one filing, shares from another)."""
            if bases:
                is_reviewed, split_date = True, b["split_date"]
            else:
                is_reviewed, split_date = reviewed_match(b["between"], b["ratio_hint"])
            restated_in = filing_at(b["between"][1])
            # S-02c: only a reviewed split names its ratio and gets adjusted values; the guard
            # alone failed a hand-check of 30 (IPOs and mergers read as splits, ratios off)
            filed_where = (f"restated in the {restated_in['form']} filed "
                           f"{restated_in['filed_date']}" if restated_in
                           else "restated in a later filing")  # fmt: skip
            earlier = b.get("earlier", [])
            for e in earlier if not bases else []:
                e["split_date"] = reviewed_match(e["between"], e["ratio_hint"])[1]
            left, right = b["between"]
            also = "".join(f" An earlier split ({e['ratio_hint']}"
                           + (f", {month(e['split_date'])}" if e["split_date"] else "")
                           + f") also separates {e['between'][0]} and {e['between'][1]}."
                           for e in earlier)  # fmt: skip
            if is_reviewed and not b.get("in_order", True):
                # PM-approved copy (2026-11-25): the page marks each pre-split cell
                lead = (f"{b['ratio_hint']} split, {month(split_date)}: shares" if split_date
                        else "Shares")  # fmt: skip
                marked = "marked years" if period == "annual" else "marked quarters"
                text = (f"{lead} and per-share figures in the {marked} (filed before the split) "
                        "are on the pre-split share basis, as reported in the filing each "
                        f"cites; later filings restated some periods, so {left} and {right} "
                        f"are on different share bases.{also} They are not adjusted.")  # fmt: skip
            elif is_reviewed:
                lead = (f"{b['ratio_hint']} split, {month(split_date)}: shares" if split_date
                        else "Shares")  # fmt: skip
                where = "" if split_date else f", {filed_where}"
                text = (f"{lead} and per-share figures before {right} are on the pre-split "
                        "share basis, as reported in the filing each cites; later filings "
                        f"restated some {'years' if period == 'annual' else 'periods'} for a "
                        f"stock split ({b['ratio_hint']}{where}), so {left} and {right} are on "
                        f"different share bases.{also} They are not adjusted.")  # fmt: skip
            else:
                text = (f"The share basis changes here ({filed_where}): shares and per-share "
                        f"figures before {right} are on the earlier share basis, as reported in "
                        f"the filing each cites, so {left} and {right} are on different share "
                        "bases. They are not adjusted.")  # fmt: skip
            return text, split_date, restated_in, is_reviewed

        for m in [r.metric for r in rows if r.metric in breaks]:
            v = breaks[m]
            text, split_date, restated_in, is_reviewed = note(v)
            if text not in notes:
                notes.append(text)
            v["text"], v["split_date"], v["restated_in"] = text, split_date, restated_in
            v["reviewed"] = is_reviewed
            v.pop("in_order", None)
            if not is_reviewed:  # about 80% of unreviewed ratios were wrong: never shown
                v["ratio_hint"] = None
    for r in rows:
        r.split_break = breaks.get(r.metric)
    reviewed_breaks = breaks if breaks and next(iter(breaks.values()))["reviewed"] else {}
    if bases and reviewed_breaks:
        brk = next(iter(reviewed_breaks.values()))
        adjusted = statements_service.basis_adjusted(db, cik, rows, bases, counted, brk, as_of)
    else:
        adjusted = statements_service.split_adjusted(db, cik, rows, reviewed_breaks, as_of)
    if adjusted:
        a = next(iter(adjusted.values()))
        more = "".join(f", and {e['ratio']} before {e['before']} from the "
                       f"{e['source']['form']} filed {e['source']['filed_date']}"
                       for e in a.get("earlier", []))  # fmt: skip
        notes.append(f"Split-adjusted values ({a['ratio']}) are given beside the as-filed ones "
                     f"for shares and per-share figures, derived from the "
                     f"{a['source']['form']} filed {a['source']['filed_date']}{more}; the "
                     "as-filed values stay the default.")  # fmt: skip
        for r in rows:
            r.split_adjusted = adjusted.get(r.metric)
    if as_of:
        notes.append(as_of_note(as_of))
    return StatementOut(
        cik=cik, statement=statement, period=period,
        as_of=as_of.isoformat() if as_of else None, reporting_currency=currency,
        mapping_version=MAPPING_VERSION, fiscal_year_end=company.fiscal_year_end,
        label_basis=periods.label_basis(periods.convention(company)),
        columns=columns, rows=rows, notes=notes,
    )  # fmt: skip


@router.get(
    "/{cik}/overview",
    responses=_ERRORS,
    summary="Everything known about a company, for one page (keyed; any company)",
    description="The public overview's payload and as_of rules for any company: identity, key "
    "figures with TTM, ten fiscal years, statements, cover, filings, leadership, events, "
    "ownership, auditor, segments and more. Built from stored data only, never calls the SEC. "
    "The demo key reaches the showcase companies only.",
)
def keyed_overview(
    request: Request,
    response: Response,
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Point in time, as for the public overview"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    from app.services import company_overview as overview_service

    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    # the demo key is held to the showcase by require_reader (403 demo_scope)
    if as_of is not None:
        if as_of > date.today():
            raise APIError(422, "invalid_parameter", "as_of cannot be in the future.")
        first = overview_service.first_filing_date(db, cik)
        if first is None or as_of < first:
            when = f"{first.day} {first:%b %Y}" if first else "that date"
            raise APIError(
                422, "invalid_parameter", f"No filings before {when}; pick a later date."
            )
    body = overview_service.build(db, cik, as_of=as_of)
    if body is None:
        raise APIError(404, "company_not_found", "No company with this CIK is loaded.")
    response.headers["Cache-Control"] = "private, no-store"
    return body


@router.get(
    "/{cik}/dividends",
    responses=_ERRORS,
    summary="Dividends declared per share by period, each with its filing; payout ratio, "
    "possibly special dividends, split-adjusted history",
    dependencies=[Depends(strict_query)],
)
def dividends(
    request: Request,
    cik: str = Path(max_length=13),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    periods_: int | None = Query(None, alias="periods", ge=1, le=80,
                                 description="Up to 20 annual, 80 quarterly"),  # fmt: skip
    as_of: date | None = Query(None, description="Only figures filed by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    """Q-04 (docs/contracts/dividends.md): the statements' own columns, selection and split
    rule; no yield until prices exist. Information, not signals."""
    from app.services import dividends as dividends_service

    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    most = 20 if period == "annual" else 80
    if periods_ is not None and periods_ > most:
        raise APIError(422, "invalid_parameter", f"periods is at most {most} for {period}.")
    out = dividends_service.build(db, company, period, periods_, as_of)
    if getattr(request.state, "demo", False) and len(out["data"]) > 10:
        out["data"] = out["data"][-10:]
        out["notes"].append("The demo key shows at most 10 periods; this list was trimmed.")
    if as_of:
        out["notes"].append(as_of_note(as_of))
    return {"cik": cik, "period": period, "as_of": as_of.isoformat() if as_of else None,
            **out, "labels": {"basis_note": "As reported: each value in the share basis of "
                              "the filing it cites."}}  # fmt: skip
