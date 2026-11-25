"""Q-06: the SEC's fails-to-deliver per company (docs/contracts/fails-to-deliver.md).
Information, not signals. Not investment advice."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.errors import APIError
from app.services import fails_to_deliver

router = APIRouter(tags=["connections"])  # beside the holders, on the Ownership tab
MAX_DAYS = 366


@router.get(
    "/v1/companies/{cik}/fails-to-deliver",
    responses=_ERRORS,
    summary="The SEC's fails-to-deliver for the company's shares, by settlement date",
    description="One sub-table per symbol and share class, never summed across classes: the "
    "balance of shares that had failed to settle and were still outstanding on each settlement "
    "date, across all clearing members (NSCC), as the SEC publishes it (a running balance, not "
    "the day's new fails); the previous day's close as filed; the value derived. From July "
    "2009; the SEC file is named. Information, not signals. Not investment advice.",
)
def company_fails_to_deliver(
    cik: str = Path(max_length=13),
    since: date | None = Query(None, description="Settlement dates on or after this date"),
    until: date | None = Query(None, description="Settlement dates on or before this date"),
    as_of: date | None = Query(None, description="Only files the SEC had published by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    if since and until and since > until:
        raise APIError(422, "invalid_parameter", "since must be on or before until.")
    if since and until and (until - since).days > MAX_DAYS:
        raise APIError(422, "invalid_parameter", f"At most {MAX_DAYS} days from since to until.")
    out = fails_to_deliver.build(db, cik, since, until, as_of)
    out["as_of"] = as_of.isoformat() if as_of else None
    return out
