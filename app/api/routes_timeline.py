"""X-05: a company's events on one timeline (docs/api-contracts-explorer.md)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.errors import APIError
from app.schemas.timeline import TimelineMeta, TimelineOut
from app.services import timeline

router = APIRouter(prefix="/v1/companies", tags=["companies"])


@router.get(
    "/{cik}/timeline",
    response_model=TimelineOut,
    responses=_ERRORS,
    summary="Filings, 8-K events, officer and auditor changes, IPO milestones, insider signals "
    "and 13F quarters on one timeline",
)
def get_timeline(
    cik: str = Path(max_length=13),
    types: str | None = Query(
        None, max_length=200, description="Comma-separated: " + ", ".join(timeline.TYPES)
    ),  # fmt: skip
    from_: date | None = Query(None, alias="from", description="Items dated on or after"),
    to: date | None = Query(None, description="Items dated on or before"),
    as_of: date | None = Query(None, description="Only what was filed by this date"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=100),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    """Information, not signals. Built from the data stored here; every item links its filing
    (a 13F quarter points to /ownership, which lists each holder's filing)."""
    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    kinds = tuple(t.strip() for t in types.split(",") if t.strip()) if types else timeline.TYPES
    unknown = [t for t in kinds if t not in timeline.TYPES]
    if unknown:
        raise APIError(422, "invalid_parameter", f"Unknown timeline type: {', '.join(unknown)}.")
    if from_ and to and from_ > to:
        raise APIError(422, "invalid_parameter", "from must be on or before to.")
    try:
        offset = timeline.decode_cursor(cursor)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cursor is not valid.") from exc
    items = timeline.build(db, company, kinds, from_, to, as_of, need=offset + limit + 1)
    page = items[offset : offset + limit]
    more = len(items) > offset + limit
    return TimelineOut(
        cik=cik, as_of=as_of.isoformat() if as_of else None, data=page,
        meta=TimelineMeta(limit=limit, has_more=more,
                          next_cursor=timeline.encode_cursor(offset + limit) if more else None),
        notes=timeline.NOTES,
    )  # fmt: skip
