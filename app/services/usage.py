"""API usage metering and quota checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import ApiUsage, CompanyWatch, utcnow


def record_usage(
    db: Session,
    api_key_id: uuid.UUID,
    request_id: str,
    route_template: str,
    http_status: int,
    units: int = 1,
    response_bytes: int | None = None,
    export_rows: int | None = None,
    occurred_at: datetime | None = None,
) -> None:
    db.add(
        ApiUsage(
            api_key_id=api_key_id,
            request_id=request_id,
            route_template=route_template,
            http_status=http_status,
            units=units,
            response_bytes=response_bytes,
            export_rows=export_rows,
            occurred_at=occurred_at or utcnow(),
        )
    )
    db.commit()


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def requests_this_month(db: Session, api_key_id: uuid.UUID, now: datetime | None = None) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(ApiUsage.units), 0)).where(
                ApiUsage.api_key_id == api_key_id, ApiUsage.occurred_at >= month_start(now)
            )
        )
        or 0
    )


def usage_summary(db: Session, api_key_id: uuid.UUID, start: datetime, end: datetime) -> dict:
    base = select(
        func.count(ApiUsage.id),
        func.coalesce(func.sum(case((ApiUsage.http_status < 400, 1), else_=0)), 0),
        func.coalesce(func.sum(case((ApiUsage.http_status >= 400, 1), else_=0)), 0),
        func.coalesce(func.sum(ApiUsage.export_rows), 0),
        func.coalesce(
            func.sum(case((ApiUsage.export_rows.is_not(None), ApiUsage.response_bytes), else_=0)),
            0,
        ),
        func.coalesce(func.sum(ApiUsage.response_bytes), 0),
    ).where(
        ApiUsage.api_key_id == api_key_id,
        ApiUsage.occurred_at >= start,
        ApiUsage.occurred_at < end,
    )
    total, ok, errors, export_rows, export_bytes, total_bytes = db.execute(base).one()
    by_route_rows = db.execute(
        select(ApiUsage.route_template, func.count(ApiUsage.id))
        .where(
            ApiUsage.api_key_id == api_key_id,
            ApiUsage.occurred_at >= start,
            ApiUsage.occurred_at < end,
        )
        .group_by(ApiUsage.route_template)
        .order_by(func.count(ApiUsage.id).desc())
    ).all()
    return {
        "total_requests": int(total),
        "successful_requests": int(ok),
        "error_requests": int(errors),
        "requests_by_route": {r: int(c) for r, c in by_route_rows},
        "export_rows": int(export_rows),
        "export_bytes": int(export_bytes),
        "response_bytes": int(total_bytes),
    }


def watched_companies_used(db: Session, api_key_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(CompanyWatch.cik))).where(
                CompanyWatch.api_key_id == api_key_id, CompanyWatch.is_active.is_(True)
            )
        )
        or 0
    )


def active_watches_used(db: Session, api_key_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(CompanyWatch.id)).where(
                CompanyWatch.api_key_id == api_key_id, CompanyWatch.is_active.is_(True)
            )
        )
        or 0
    )
