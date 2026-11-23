"""D-15: private raises from Form D (docs/contracts/private-raises.md). Self-reported by the
issuer on Form D; amounts as filed. Stored data only."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.errors import APIError
from app.services import form_d

router = APIRouter(tags=["companies"])


def _body(items, more, limit, offset) -> dict:
    return {"data": items,
            "meta": {"limit": limit, "has_more": more,
                     "next_cursor": form_d.encode_cursor(offset + limit) if more else None},
            "labels": {"basis": form_d.BASIS}, "notes": form_d.NOTES}  # fmt: skip


def _offset(cursor: str | None) -> int:
    try:
        return form_d.decode_cursor(cursor)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cursor is not valid.") from exc


@router.get("/v1/private-raises", responses=_ERRORS,
            summary="Form D private raises, newest first, filtered by industry, state, amount, "
            "date and exemption")  # fmt: skip
def list_private_raises(
    industry: str | None = Query(None, max_length=80, description="Industry group as filed"),
    state: str | None = Query(None, max_length=4, description="Issuer state or country code"),
    min_amount: float | None = Query(None, ge=0, description="Offering amount (or amount "
                                     "sold when the offering is indefinite), USD"),
    from_: date | None = Query(None, alias="from", description="Latest filing on or after"),
    to: date | None = Query(None, description="Latest filing on or before"),
    exemption: str | None = Query(None, max_length=8, description="One code, e.g. 06b, 06c"),
    min_sold: float | None = Query(None, ge=0, description="Amount sold so far (cumulative, "
                                   "latest filing), USD: what was raised"),
    order: str = Query("date", pattern="^(date|sold)$", description="date (newest first) or "
                       "sold (largest amount sold first)"),
    include_suspect: bool = Query(False, description="Also rank offerings whose self-reported "
                                  "amount is implausible (quality_status suspect_amount)"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=100),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    """Self-reported by the issuer on Form D; amounts as filed. Each offering links its
    filings on sec.gov/Archives."""
    if from_ and to and from_ > to:
        raise APIError(422, "invalid_parameter", "from must be on or before to.")
    offset = _offset(cursor)
    items, more = form_d.search(db, industry, state, min_amount, from_, to, exemption,
                                limit=limit, offset=offset, min_sold=min_sold,
                                order=order, include_suspect=include_suspect)  # fmt: skip
    return _body(items, more, limit, offset)


@router.get("/v1/companies/{cik}/private-raises", responses=_ERRORS,
            summary="One issuer's Form D offerings")  # fmt: skip
def company_private_raises(
    cik: str = Path(max_length=13),
    since: date | None = Query(None, description="Latest filing on or after"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=100),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    offset = _offset(cursor)
    items, more = form_d.search(db, start=since, cik=cik, limit=limit, offset=offset)
    return {"cik": cik, **_body(items, more, limit, offset)}
