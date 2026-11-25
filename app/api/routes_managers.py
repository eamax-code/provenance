"""Q-02: Form 13F managers (docs/contracts/managers.md): search, a manager's portfolio by
quarter with changes against the quarter before, and the most bought or sold by funds."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep
from app.api.routes_companies import _ERRORS, _parse_cik_param
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import Filing13F
from app.services import fund_managers as fm
from app.services import thirteenf
from app.services.notes import with_detail
from app.services.public import showcase_ciks

router = APIRouter(tags=["connections"])  # beside each company's institutional holders
DEMO_ROWS = 10


def _quarter(db: Session, quarter: date | None, as_of: date | None) -> date:
    latest = fm.latest_quarter(db, as_of)
    if latest is None:
        raise APIError(404, "not_found", "No Form 13F quarter is loaded yet.")
    if quarter is None:
        return latest
    if thirteenf.quarter_ends(quarter) != quarter:
        raise APIError(422, "invalid_parameter", "quarter must be a quarter end, e.g. 2026-09-30.")
    if quarter > latest:
        raise APIError(422, "invalid_parameter",
                       f"The latest complete quarter is {latest.isoformat()}.")  # fmt: skip
    return quarter


def _demo(request: Request, db: Session, settings: Settings) -> set[str] | None:
    return set(showcase_ciks(db, settings)[0]) if getattr(request.state, "demo", False) else None


@router.get("/v1/managers", responses=_ERRORS,
            summary="Form 13F managers by name or CIK")  # fmt: skip
def search_managers(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    notes = []
    if _demo(request, db, settings) is not None and limit > DEMO_ROWS:
        limit = DEMO_ROWS
        notes.append(f"The demo key shows at most {DEMO_ROWS} rows.")
    rows, more = fm.search(db, q, limit)
    return with_detail({"data": rows, "meta": {"limit": limit, "has_more": more},
                        "value_basis": "usd", "reporting_lag": fm.LAG, "notes": notes})  # fmt: skip


@router.get("/v1/managers/activity", responses=_ERRORS,
            summary="Most bought or sold by funds in a quarter (Form 13F)")  # fmt: skip
def fund_activity(
    request: Request,
    quarter: date | None = Query(None, description="A quarter end; default the latest"),
    direction: str = Query("bought", pattern="^(bought|sold)$"),
    min_holders: int = Query(20, ge=1, le=1000),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    q = _quarter(db, quarter, None)
    allowed = _demo(request, db, settings)
    notes = []
    if allowed is not None and limit > DEMO_ROWS:
        limit = DEMO_ROWS
        notes.append(f"The demo key shows at most {DEMO_ROWS} rows, from the showcase companies.")
    rows, left_out = fm.activity(db, q, direction, min_holders, limit, allowed)
    if fm.stale(db):
        notes.append(fm.STALE_NOTE)
    notes += [
        "Counts managers that filed holdings for both quarters as added, reduced or exited; new "
        "counts managers holding it now and not before. Shares are compared, never values, so "
        "price moves are not read as buying or selling.",
    ]
    if left_out:
        named = "; ".join(f"{x['name']} ({x['reason']})" for x in left_out[:5])
        notes.append(f"{len(left_out)} companies are left out: their managers' total shares more "
                     "than doubled or fell by more than half (a merger, takeover, listing, "
                     "reorganisation, stock split or a change of security), which is not funds "
                     f"buying or selling. The most widely held of them: {named}.")  # fmt: skip
    return with_detail({"quarter": q, "previous_quarter": thirteenf.previous_quarter(q),
            "direction": direction, "value_basis": "usd", "reporting_lag": fm.LAG, "data": rows,
            "labels": {"disclaimer": fm.DISCLAIMER}, "notes": notes})  # fmt: skip


@router.get("/v1/managers/{cik}", responses=_ERRORS,
            summary="A Form 13F manager's portfolio for a quarter, with changes")  # fmt: skip
def manager_portfolio(
    request: Request,
    cik: str = Path(max_length=13),
    quarter: date | None = Query(None, description="A quarter end; default the latest"),
    as_of: date | None = Query(None, description="Only filings made by this date"),
    sort: str = Query("value", pattern="^(value|change|name)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    filed = db.scalar(select(Filing13F.accession_number).where(Filing13F.filer_cik == cik).limit(1))
    if filed is None:
        raise APIError(404, "manager_not_found", "No Form 13F of this CIK is stored.")
    q = _quarter(db, quarter, as_of)
    cached, hist = fm.cached_view(db, cik, q, as_of)
    if cached is None:
        nt = fm.notice(db, cik, q, as_of)
        if nt is None:
            raise APIError(404, "not_found", f"No Form 13F holdings of this manager for "
                           f"{q.isoformat()}.")  # fmt: skip
        return with_detail({**nt, "previous_quarter": thirteenf.previous_quarter(q),
                "value_basis": "usd", "reporting_lag": fm.LAG, "positions": [], "exited": [],
                "history": fm.history(db, cik, as_of), "coverage": fm.coverage(db),
                "meta": {"limit": limit, "offset": 0, "has_more": False, "next_offset": None},
                "labels": {"disclaimer": fm.DISCLAIMER},
                "notes": ["This manager filed a 13F notice for the quarter: its holdings are "
                          "reported by the managers in reported_by."]})  # fmt: skip
    p = {k: v for k, v in cached.items() if k not in ("notes", "positions")}
    notes = list(cached["notes"]) + ([fm.STALE_NOTE] if fm.stale(db) else [])
    positions = list(cached["positions"])  # sorted here, never in the cache
    if sort == "value":
        positions.sort(key=lambda x: (p["filing"]["value_scale_suspect"], -x["value_usd"]))
    elif sort == "change":  # the absolute share change at this quarter's price per share
        positions.sort(key=lambda x: -abs((x["change"] or {}).get("shares_change") or 0)
                       * (x["value_usd"] / x["shares"] if x["shares"] else 0))  # fmt: skip
    else:
        positions.sort(key=lambda x: ((x["issuer"]["name"] or "").lower(), x["class_label"]))
    if _demo(request, db, settings) is not None and limit > DEMO_ROWS:
        limit, offset = DEMO_ROWS, 0
        notes.append(f"The demo key shows at most {DEMO_ROWS} positions.")
    page = [{k: v for k, v in x.items() if k != "key"} for x in positions[offset : offset + limit]]
    more = len(positions) > offset + limit
    return with_detail({**p, "notice_only": False, "reported_by": [], "value_basis": "usd",
            "reporting_lag": fm.LAG, "positions": page,
            "history": hist, "coverage": fm.coverage(db),
            "meta": {"limit": limit, "offset": offset, "has_more": more,
                     "next_offset": offset + limit if more else None},
            "labels": {"disclaimer": fm.DISCLAIMER}, "notes": notes})  # fmt: skip
