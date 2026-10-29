from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import ApiKey, Company, Filing, FinancialFact, utcnow
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
    FreshnessOut,
)
from app.services import freshness as freshness_service
from app.services.company_lookup import search_companies
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS, derive_quarters
from app.services.ingestion import ingest_company
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


def _company_out(c: Company, match_type: str | None = None) -> CompanyOut:
    out = CompanyOut.model_validate(c)
    out.match_type = match_type
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
    _key: ApiKey = Depends(require_api_key),
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


@router.get("/search", response_model=CompanyList, responses=_ERRORS)
def search(
    q: str = Query(min_length=1, max_length=100, description="Ticker, CIK, or company name"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(db_session),
    _key: ApiKey = Depends(require_api_key),
):
    hits, has_more = search_companies(db, q, limit)
    return CompanyList(
        data=[_company_out(h.company, h.match_type) for h in hits],
        meta=PageMeta(limit=limit, has_more=has_more),
    )


@router.get(
    "/{cik}",
    response_model=CompanyProfile,
    responses={**_ERRORS, 202: {"model": CompanyProfile, "description": "Ingestion in progress"}},
)
def profile(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key: ApiKey = Depends(require_api_key),
):
    cik = _parse_cik_param(cik)
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        if settings.on_demand_ingestion_enabled and _schedule_ingestion(cik, background, request):
            response.status_code = 202
            response.headers["Retry-After"] = "10"
            return CompanyProfile(
                cik=cik,
                legal_name="",
                ticker=None,
                exchange=None,
                source_url=f"{settings.sec_base_data_url}/submissions/CIK{cik}.json",
                first_detected_at=utcnow(),
                last_processed_at=None,
                quality_status="unavailable",
                ingestion_status="processing",
            )
        raise APIError(404, "company_not_found", "No company with this CIK is available.")

    out = CompanyProfile.model_validate(company)
    out.filings_count = int(db.scalar(select(func.count(Filing.id)).where(Filing.cik == cik)) or 0)
    out.facts_count = int(
        db.scalar(select(func.count(FinancialFact.id)).where(FinancialFact.cik == cik)) or 0
    )
    if company.last_processed_at is None:
        scheduled = settings.on_demand_ingestion_enabled and _schedule_ingestion(
            cik, background, request
        )
        out.ingestion_status = (
            "processing" if scheduled else ("failed" if company.last_fetch_error else "pending")
        )
        if scheduled:
            response.status_code = 202
            response.headers["Retry-After"] = "10"
    return out


@router.get("/{cik}/filings", response_model=FilingList, responses=_ERRORS)
def filings(
    cik: str = Path(max_length=13),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    form_type: str | None = Query(None, max_length=20),
    since: date | None = Query(None, description="Only filings with filing_date >= since"),
    db: Session = Depends(db_session),
    _key: ApiKey = Depends(require_api_key),
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


@router.get("/{cik}/facts", response_model=FactList, responses=_ERRORS)
def facts(
    cik: str = Path(max_length=13),
    metric: str | None = Query(None, description=f"One of {', '.join(SUPPORTED_METRICS)}"),
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
    db: Session = Depends(db_session),
    _key: ApiKey = Depends(require_api_key),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    if metric is not None and metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    stmt = select(FinancialFact).where(FinancialFact.cik == cik, FinancialFact.derived.is_(False))
    if metric:
        stmt = stmt.where(FinancialFact.metric == metric)
    if from_:
        stmt = stmt.where(FinancialFact.period_end >= from_)
    if to:
        stmt = stmt.where(FinancialFact.period_end <= to)
    if form_type:
        stmt = stmt.where(func.upper(FinancialFact.form_type) == form_type.upper())
    if period != "all":
        stmt = stmt.where(FinancialFact.period_class == period)
    rows = db.scalars(stmt).all()

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

    selected.sort(
        key=lambda f: (f.period_end, f.period_start or date.min, f.metric, f.source_tag),
        reverse=True,
    )
    total = len(selected)
    page = selected[offset : offset + limit]
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
        notes=notes,
    )


@router.get("/{cik}/freshness", response_model=FreshnessOut, responses=_ERRORS)
def freshness(
    cik: str = Path(max_length=13),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key: ApiKey = Depends(require_api_key),
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
        best = max(preferred, key=lambda r: (r.filed_date or date.min, r.accession_number or ""))
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


def _derived_out(cik: str, d, source_rows: list[FinancialFact]) -> FactOut:
    now_rows = [r for r in source_rows if r.accession_number == d.accession_number]
    detected = min((r.first_detected_at for r in now_rows), default=None)
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
        first_detected_at=detected or utcnow(),
        processed_at=processed or utcnow(),
    )
