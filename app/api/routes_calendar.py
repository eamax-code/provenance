"""X-15: calendars for a company, a watchlist and a list of companies
(docs/contracts/calendar.md). Derived dates say derived and give their rule."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, require_reader, settings_dep
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.api.routes_watchlists import _ciks as watchlist_ciks
from app.api.routes_watchlists import _get as get_watchlist
from app.api.routes_watchlists import _public_id
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import ApiKey
from app.services import company_calendar as cal
from app.services.sec_client import normalize_cik

router = APIRouter(tags=["companies"])
MAX_CIKS = 50
_KINDS_DOC = "Comma-separated: " + ", ".join(cal.KINDS)


def _range(from_: date | None, to: date | None, kinds: str | None) -> tuple:
    today = date.today()
    start = from_ or today - timedelta(days=90)
    end = to or today + timedelta(days=180)
    if start > end:
        raise APIError(422, "invalid_parameter", "from must be on or before to.")
    if (end - start).days > cal.MAX_RANGE_DAYS:
        raise APIError(422, "invalid_parameter",
                       f"from and to can be at most {cal.MAX_RANGE_DAYS} days apart.")  # fmt: skip
    wanted = tuple(k.strip() for k in kinds.split(",") if k.strip()) if kinds else cal.KINDS
    unknown = [k for k in wanted if k not in cal.KINDS]
    if unknown:
        raise APIError(422, "invalid_parameter", f"Unknown calendar kind: {', '.join(unknown)}.")
    return start, end, wanted


def _body(start, end, data, **extra) -> dict:
    return {**extra, "from": start.isoformat(), "to": end.isoformat(), "data": data,
            "notes": cal.NOTES}  # fmt: skip


@router.get(
    "/v1/companies/{cik}/calendar",
    responses=_ERRORS,
    summary="Filing deadlines (derived), late notices, IPO dates and Form 144 windows",
)
def company_calendar(
    cik: str = Path(max_length=13),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    kinds: str | None = Query(None, max_length=200, description=_KINDS_DOC),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    start, end, wanted = _range(from_, to, kinds)
    return _body(start, end, cal.for_company(db, company, start, end, wanted), cik=cik)


@router.get("/v1/watchlists/{wid}/calendar", responses=_ERRORS, tags=["watches"],
            summary="The calendar of every company in one of your watchlists")  # fmt: skip
def watchlist_calendar(
    wid: str = Path(max_length=40),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    kinds: str | None = Query(None, max_length=200, description=_KINDS_DOC),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
) -> dict:
    w = get_watchlist(db, key, wid)
    start, end, wanted = _range(from_, to, kinds)
    data, truncated = cal.for_companies(db, watchlist_ciks(db, w), start, end, wanted)
    return _body(start, end, data, id=_public_id(w),
                 meta={"truncated": truncated, "cap": cal.WATCHLIST_CAP})  # fmt: skip


@router.get(
    "/v1/calendar",
    responses=_ERRORS,
    summary="The calendar of up to 50 companies (a watchlist kept in the browser)",
)
def calendar_for_ciks(
    request: Request,
    ciks: str = Query(..., max_length=700, description="Comma-separated CIKs, at most 50"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    kinds: str | None = Query(None, max_length=200, description=_KINDS_DOC),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    try:
        wanted_ciks = list(dict.fromkeys(normalize_cik(c) for c in ciks.split(",") if c.strip()))
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "ciks must be 1-10 digit CIKs.") from exc
    if not wanted_ciks or len(wanted_ciks) > MAX_CIKS:
        raise APIError(422, "invalid_parameter", f"Give 1 to {MAX_CIKS} CIKs.")
    if getattr(request.state, "demo", False):
        from app.services.public import showcase_ciks

        allowed = set(showcase_ciks(db, settings)[0])
        if any(c not in allowed for c in wanted_ciks):
            raise APIError(403, "demo_scope",
                           "The demo key covers the public showcase companies only.")  # fmt: skip
    start, end, wanted = _range(from_, to, kinds)
    data, truncated = cal.for_companies(db, wanted_ciks, start, end, wanted)
    return _body(start, end, data, ciks=wanted_ciks,
                 meta={"truncated": truncated, "cap": cal.WATCHLIST_CAP})  # fmt: skip
