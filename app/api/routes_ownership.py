"""Institutional ownership of a company from Form 13F (launch plan E-1)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.errors import APIError
from app.schemas.common import PageMeta
from app.schemas.ownership import OwnershipOut
from app.services import segments, thirteenf

router = APIRouter(prefix="/v1/companies", tags=["connections"])


@router.get(
    "/{cik}/ownership",
    response_model=OwnershipOut,
    responses=_ERRORS,
    summary="Institutional holders from Form 13F: the latest complete quarter",
)
def get_ownership(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only 13F filings made by this date"),
    limit: int = Query(15, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    b = thirteenf.for_company(db, company, as_of, limit, offset)
    if b is None:
        raise APIError(404, "no_ownership_data",
                       "No Form 13F positions are loaded for this company.")  # fmt: skip
    holders = b.pop("top_holders")
    more = b.pop("has_more")
    return OwnershipOut(
        cik=cik, data=holders, as_of=as_of.isoformat() if as_of else None,
        meta=PageMeta(limit=limit, offset=offset, has_more=more,
                      next_offset=offset + limit if more else None),
        **b,
    )  # fmt: skip


@router.get(
    "/{cik}/segments",
    responses=_ERRORS,
    summary="Revenue and profit by business segment, geography and product, from the annual report",
)
def get_segments(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only annual reports filed by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    """E-4: the latest annual report's segments, up to three fiscal years, each kind with its
    status (ok when the segments add up to the consolidated figure or a reconciling item is
    tagged; otherwise unreconciled)."""
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    b = segments.for_company(db, cik, as_of)
    if b is None:
        raise APIError(404, "no_segment_data", "No segment figures are loaded for this company.")
    return {"cik": cik, "as_of": as_of.isoformat() if as_of else None, **b}
