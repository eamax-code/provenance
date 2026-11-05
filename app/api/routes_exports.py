from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.db.models import ApiKey, Company, FinancialFact, MartCompanyPeriod
from app.schemas.common import ErrorEnvelope
from app.services.exports import (
    PERIOD_COLUMNS,
    export_filename,
    period_row,
    render_csv,
    render_json,
    render_rows_csv,
    render_rows_json,
)
from app.services.fact_normalizer import MAPPING_VERSION, SUPPORTED_METRICS
from app.services.sec_client import normalize_cik

router = APIRouter(prefix="/v1/exports", tags=["exports"])
MAX_CIKS = 50


@router.get(
    "/facts",
    responses={
        200: {"content": {"text/csv": {}, "application/json": {}}, "description": "Bounded export"},
        401: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
    summary="Export normalized facts (bounded) as CSV or JSON",
)
def export_facts(
    request: Request,
    metric: str | None = Query(None),
    ciks: str | None = Query(None, description="Comma-separated CIKs (max 50)"),
    format: str = Query("csv", pattern="^(csv|json)$"),
    period: str = Query("all", pattern="^(annual|quarterly|all)$"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    limit: int | None = Query(None, ge=1),
    include_ambiguous: bool = Query(False),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    if metric is not None and metric not in SUPPORTED_METRICS:
        raise APIError(
            422, "invalid_parameter", f"metric must be one of: {', '.join(SUPPORTED_METRICS)}."
        )
    cik_list = _cik_list(ciks)
    if not metric and not cik_list:
        raise APIError(
            422,
            "invalid_parameter",
            "Provide a metric and/or a bounded list of ciks; "
            "full-universe exports are not allowed.",
        )
    requested = _row_limit(limit, key, settings)

    stmt = select(FinancialFact).where(FinancialFact.derived.is_(False))
    if metric:
        stmt = stmt.where(FinancialFact.metric == metric)
    if cik_list:
        stmt = stmt.where(FinancialFact.cik.in_(cik_list))
    if period != "all":
        stmt = stmt.where(FinancialFact.period_class == period)
    if from_:
        stmt = stmt.where(FinancialFact.period_end >= from_)
    if to:
        stmt = stmt.where(FinancialFact.period_end <= to)
    if not include_ambiguous:
        stmt = stmt.where(FinancialFact.quality_status.in_(["ok", "partial"]))
    stmt = stmt.order_by(
        FinancialFact.cik,
        FinancialFact.metric,
        FinancialFact.period_end.desc(),
        FinancialFact.filed_date.desc(),
    ).limit(requested + 1)
    rows = db.scalars(stmt).all()
    truncated = len(rows) > requested
    rows = rows[:requested]

    now = datetime.now(UTC)
    filename = export_filename(metric, cik_list, format, now)
    headers = _headers(filename, len(rows), truncated, requested)
    if format == "csv":
        body = render_csv(rows)
        media = "text/csv; charset=utf-8"
    else:
        body = render_json(
            rows,
            {
                "rows_returned": len(rows),
                "row_limit": requested,
                "truncated": truncated,
                "mapping_version": MAPPING_VERSION,
                "generated_at": now.isoformat().replace("+00:00", "Z"),
                "source": "SEC EDGAR; independent service, not affiliated with the SEC",
            },
        )
        media = "application/json"
    request.state.export_rows = len(rows)
    request.state.export_rows_requested = requested
    return Response(content=body, media_type=media, headers=headers)


@router.get(
    "/company-years",
    responses={
        200: {"content": {"text/csv": {}, "application/json": {}}, "description": "Bounded export"},
        401: {"model": ErrorEnvelope},
        413: {"model": ErrorEnvelope},
        422: {"model": ErrorEnvelope},
    },
    summary="Export one row per company and fiscal year, five figures side by side",
    description="From mart_company_period: revenue, operating income, net income, total assets "
    "and operating cash flow in USD as reported in each fiscal year's annual report, with each "
    "figure's filing link. Give ciks (max 50) and/or a fiscal year range; one year across all "
    "companies is allowed, up to your plan's export row limit.",
)
def export_company_years(
    request: Request,
    ciks: str | None = Query(None, description="Comma-separated CIKs (max 50)"),
    from_year: int | None = Query(None, ge=1990, le=2100),
    to_year: int | None = Query(None, ge=1990, le=2100),
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int | None = Query(None, ge=1),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    cik_list = _cik_list(ciks)
    if not cik_list and (from_year is None or from_year != to_year):
        raise APIError(
            422,
            "invalid_parameter",
            "Provide ciks, or one fiscal year (from_year = to_year) across all companies; "
            "full-universe exports are not allowed.",
        )
    requested = _row_limit(limit, key, settings)
    stmt = select(MartCompanyPeriod, Company.legal_name).join(
        Company, Company.cik == MartCompanyPeriod.cik
    )
    if cik_list:
        stmt = stmt.where(MartCompanyPeriod.cik.in_(cik_list))
    if from_year is not None:
        stmt = stmt.where(MartCompanyPeriod.fiscal_year >= from_year)
    if to_year is not None:
        stmt = stmt.where(MartCompanyPeriod.fiscal_year <= to_year)
    stmt = stmt.order_by(MartCompanyPeriod.cik, MartCompanyPeriod.fiscal_year.desc())
    found = db.execute(stmt.limit(requested + 1)).all()
    truncated = len(found) > requested
    rows = [period_row(r, name) for r, name in found[:requested]]

    now = datetime.now(UTC)
    filename = export_filename(None, cik_list, format, now, kind="company_years")
    headers = _headers(filename, len(rows), truncated, requested)
    if format == "csv":
        body, media = render_rows_csv(rows, PERIOD_COLUMNS), "text/csv; charset=utf-8"
    else:
        meta = {
            "rows_returned": len(rows),
            "row_limit": requested,
            "truncated": truncated,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "source": "SEC EDGAR; independent service, not affiliated with the SEC",
        }
        body, media = render_rows_json(rows, meta), "application/json"
    request.state.export_rows = len(rows)
    request.state.export_rows_requested = requested
    return Response(content=body, media_type=media, headers=headers)


def _cik_list(ciks: str | None) -> list[str]:
    if not ciks:
        return []
    raw = [c for c in ciks.split(",") if c.strip()]
    if len(raw) > MAX_CIKS:
        raise APIError(422, "invalid_parameter", f"At most {MAX_CIKS} CIKs per export.")
    try:
        return sorted({normalize_cik(c) for c in raw})
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "ciks must be 1-10 digit values.") from exc


def _row_limit(limit: int | None, key: ApiKey, settings: Settings) -> int:
    max_rows = plan_limits(key.plan, settings)["max_export_rows"]
    requested = limit or max_rows
    if requested > max_rows:
        raise APIError(
            413, "export_limit_exceeded", f"limit may not exceed {max_rows} rows for your plan."
        )
    return requested


def _headers(filename: str, rows: int, truncated: bool, requested: int) -> dict:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Rows": str(rows),
        "X-Export-Truncated": "true" if truncated else "false",
        "X-Export-Row-Limit": str(requested),
        "X-Data-Source": (
            "SEC EDGAR (https://www.sec.gov). Independent service, not affiliated with the SEC."
        ),
    }
