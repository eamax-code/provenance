"""Q-07: activist stakes (Schedule 13D) per company and across companies
(docs/contracts/activists.md). Information, not signals. Not investment advice."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.config import Settings
from app.core.errors import APIError
from app.services import activists
from app.services.public import showcase_ciks

router = APIRouter(tags=["connections"])  # beside the holders above 5%
MAX_DAYS = 366
MAX_OFFSET = 5000
DEMO_ROWS = 10


@router.get(
    "/v1/companies/{cik}/activists",
    responses=_ERRORS,
    summary="The company's Schedule 13D filers: stake, group, stated purpose and amendments",
    description="One entry per filer chain (a 13D and its 13D/As): the group's percent and shares "
    "as filed, the change at each amendment, a switch from a 13G, and Item 4 (Purpose of "
    "Transaction) quoted as filed with its own filing cited. Structured Schedules 13D since "
    "December 2024. Information, not signals. Not investment advice.",
)
def company_activists(
    cik: str = Path(max_length=13),
    status: str = Query("current", pattern="^(current|all)$"),
    as_of: date | None = Query(None, description="Only filings made by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    out = activists.for_company(db, cik, status, as_of)
    out["status"], out["as_of"] = status, as_of.isoformat() if as_of else None
    return out


@router.get(
    "/v1/activists",
    responses=_ERRORS,
    summary="Schedule 13D filings across companies: new, increased, decreased, exited, switched",
    description="One row per 13D or 13D/A filed in the window (at most 366 days; the last 30 by "
    "default), newest first, its kind read from the filer's chain. kind=new lists every "
    "original 13D (a row reads switched when the filer filed a 13G first). Information, not "
    "signals. Not investment advice.",
)
def activist_stakes(
    request: Request,
    since: date | None = Query(None, description="Filed on or after this date"),
    until: date | None = Query(None, description="Filed on or before this date"),
    kind: str = Query("new", pattern="^(" + "|".join(activists.KINDS) + ")$"),
    min_percent: float | None = Query(None, ge=5, le=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    until = until or date.today()
    since = since or until - timedelta(days=30)
    if since > until:
        raise APIError(422, "invalid_parameter", "since must be on or before until.")
    if (until - since).days > MAX_DAYS:
        raise APIError(422, "invalid_parameter", f"At most {MAX_DAYS} days from since to until.")
    notes: list[str] = []
    allowed = set(showcase_ciks(db, settings)[0]) if getattr(request.state, "demo", False) else None
    if allowed is not None:
        limit, offset = min(limit, DEMO_ROWS), 0
    rows = activists.across(db, since, until, kind, min_percent, allowed)
    page, more = rows[offset : offset + limit], len(rows) > offset + limit
    if allowed is not None and more:
        more = False
        notes.append(f"The demo key shows at most {DEMO_ROWS} rows, from the showcase "
                     "companies; this list was trimmed.")  # fmt: skip
    notes.append("kind: new is an original 13D (switched when the filer, or a reporting person "
                 "in common, filed a 13G first); increased or decreased an amendment moving the "
                 "percent by 0.1 points or more; exited one reporting under 5%; amended any "
                 "other amendment (kind=all).")  # fmt: skip
    return {
        "since": since.isoformat(), "until": until.isoformat(), "kind": kind,
        "data": page,
        "meta": {"limit": limit, "offset": offset, "has_more": more,
                 "next_offset": offset + limit if more else None},
        "coverage": activists.COVERAGE,
        "labels": {"disclaimer": activists.DISCLAIMER},
        "notes": notes,
    }  # fmt: skip
