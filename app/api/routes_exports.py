from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.db.models import ApiKey, FinancialFact
from app.schemas.common import ErrorEnvelope
from app.services.exports import export_filename, render_csv, render_json
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
    cik_list: list[str] = []
    if ciks:
        raw = [c for c in ciks.split(",") if c.strip()]
        if len(raw) > MAX_CIKS:
            raise APIError(422, "invalid_parameter", f"At most {MAX_CIKS} CIKs per export.")
        try:
            cik_list = sorted({normalize_cik(c) for c in raw})
        except ValueError as exc:
            raise APIError(422, "invalid_parameter", "ciks must be 1-10 digit values.") from exc
    if not metric and not cik_list:
        raise APIError(
            422,
            "invalid_parameter",
            "Provide a metric and/or a bounded list of ciks; "
            "full-universe exports are not allowed.",
        )
    max_rows = plan_limits(key.plan, settings)["max_export_rows"]
    requested = limit or max_rows
    if requested > max_rows:
        raise APIError(
            413, "export_limit_exceeded", f"limit may not exceed {max_rows} rows for your plan."
        )

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
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Export-Rows": str(len(rows)),
        "X-Export-Truncated": "true" if truncated else "false",
        "X-Export-Row-Limit": str(requested),
        "X-Data-Source": (
            "SEC EDGAR (https://www.sec.gov). Independent service, not affiliated with the SEC."
        ),
    }
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
