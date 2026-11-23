"""X-07: watchlists stored per API key (docs/api-contracts-explorer.md). Named lists of companies
with chosen columns; rows per company; the companies' timeline items in one feed; and "watch",
which makes the existing signed company watches. Another key's list is 404, never 403.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.core.config import Settings
from app.core.errors import APIError
from app.core.plans import PLANS
from app.db.models import ApiKey, Company, Filing, Watchlist, WatchlistCompany, utcnow
from app.services import intel, ratios, timeline
from app.services.fact_normalizer import SUPPORTED_METRICS
from app.services.sec_client import normalize_cik

router = APIRouter(prefix="/v1/watchlists", tags=["watches"])

SPECIAL = ("reporting_currency", "latest_filing", "last_event", "holders_change")
DERIVED = ("gross_margin", "operating_margin", "net_margin", "free_cash_flow", "current_ratio",
           "debt_to_equity")  # fmt: skip
COLUMNS = tuple(SUPPORTED_METRICS) + DERIVED + SPECIAL
EVENT_KINDS = ("8k_item", "officer_change", "auditor_change", "ipo", "insider")


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    ciks: list[str] = Field(default_factory=list, max_length=500)
    columns: list[str] = Field(default_factory=list, max_length=50)


class WatchlistPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    ciks: list[str] | None = Field(None, max_length=500)
    columns: list[str] | None = Field(None, max_length=50)


class WatchIn(BaseModel):
    destination_type: str = Field(pattern="^(webhook|email)$")
    destination: str = Field(max_length=500)
    event_types: list[str] | None = None


def _limits(key: ApiKey):
    plan = PLANS.get(key.plan) or PLANS["free"]
    return plan.max_watchlists, plan.max_watchlist_companies, plan.max_watchlist_columns


def _public_id(w: Watchlist) -> str:
    return f"wl_{w.id.hex}"


def _get(db: Session, key: ApiKey, wid: str) -> Watchlist:
    try:
        raw = uuid.UUID(wid.removeprefix("wl_"))
    except ValueError as exc:
        raise APIError(404, "watchlist_not_found", "No such watchlist.") from exc
    w = db.get(Watchlist, raw)
    if w is None or w.api_key_id != key.id:  # another key's list is simply not found
        raise APIError(404, "watchlist_not_found", "No such watchlist.")
    return w


def _ciks(db: Session, w: Watchlist) -> list[str]:
    return list(db.scalars(select(WatchlistCompany.cik).where(WatchlistCompany.watchlist_id
                                                              == w.id)
                           .order_by(WatchlistCompany.position)))  # fmt: skip


def _out(db: Session, w: Watchlist) -> dict:
    return {"id": _public_id(w), "name": w.name, "ciks": _ciks(db, w),
            "columns": json.loads(w.columns), "created_at": w.created_at,
            "updated_at": w.updated_at}  # fmt: skip


def _validate(db: Session, key: ApiKey, ciks: list[str] | None, columns: list[str] | None):
    _, max_companies, max_columns = _limits(key)
    norm = None
    if ciks is not None:
        try:
            norm = list(dict.fromkeys(normalize_cik(c) for c in ciks))
        except ValueError as exc:
            raise APIError(422, "invalid_parameter", "Each cik must be 1-10 digits.") from exc
        if len(norm) > max_companies:
            raise APIError(422, "watchlist_limit_reached",
                           f"A watchlist holds up to {max_companies} companies.")  # fmt: skip
        known = set(db.scalars(select(Company.cik).where(Company.cik.in_(norm)))) if norm else set()
        unknown = [c for c in norm if c not in known]
        if unknown:
            raise APIError(422, "invalid_parameter", f"Unknown companies: {', '.join(unknown)}.")
    if columns is not None:
        bad = [c for c in columns if c not in COLUMNS]
        if bad:
            raise APIError(422, "invalid_parameter", f"Unknown columns: {', '.join(bad)}.")
        if len(columns) > max_columns:
            raise APIError(422, "watchlist_limit_reached",
                           f"A watchlist shows up to {max_columns} columns.")  # fmt: skip
    return norm


def _set_ciks(db: Session, w: Watchlist, ciks: list[str]) -> None:
    db.execute(delete(WatchlistCompany).where(WatchlistCompany.watchlist_id == w.id))
    for i, c in enumerate(ciks):
        db.add(WatchlistCompany(watchlist_id=w.id, cik=c, position=i))


@router.post("", status_code=201, summary="Create a watchlist")
def create(body: WatchlistIn, db: Session = Depends(db_session),
           key: ApiKey = Depends(require_api_key)):  # fmt: skip
    max_lists, _, _ = _limits(key)
    used = db.scalar(select(func.count()).select_from(Watchlist)
                     .where(Watchlist.api_key_id == key.id))  # fmt: skip
    if used >= max_lists:
        raise APIError(422, "watchlist_limit_reached",
                       f"Your plan allows {max_lists} watchlists.")  # fmt: skip
    ciks = _validate(db, key, body.ciks, body.columns) or []
    now = utcnow()
    w = Watchlist(api_key_id=key.id, name=body.name.strip(), columns=json.dumps(body.columns),
                  created_at=now, updated_at=now)  # fmt: skip
    db.add(w)
    db.flush()
    _set_ciks(db, w, ciks)
    db.commit()
    return _out(db, w)


@router.get("", summary="Your watchlists")
def list_(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10_000),
          db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)):  # fmt: skip
    q = select(Watchlist).where(Watchlist.api_key_id == key.id).order_by(Watchlist.created_at)
    rows = list(db.scalars(q.offset(offset).limit(limit + 1)))
    return {"data": [_out(db, w) for w in rows[:limit]],
            "meta": {"limit": limit, "offset": offset, "has_more": len(rows) > limit}}  # fmt: skip


@router.get("/{wid}", summary="A watchlist")
def read(wid: str = Path(max_length=40), db: Session = Depends(db_session),
         key: ApiKey = Depends(require_api_key)):  # fmt: skip
    return _out(db, _get(db, key, wid))


@router.patch("/{wid}", summary="Rename a watchlist or change its companies or columns")
def update(body: WatchlistPatch, wid: str = Path(max_length=40),
           db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)):  # fmt: skip
    w = _get(db, key, wid)
    ciks = _validate(db, key, body.ciks, body.columns)
    if body.name is not None:
        w.name = body.name.strip()
    if body.columns is not None:
        w.columns = json.dumps(body.columns)
    if ciks is not None:
        _set_ciks(db, w, ciks)
    w.updated_at = utcnow()
    db.commit()
    return _out(db, w)


@router.delete("/{wid}", status_code=204, summary="Delete a watchlist (its watches stay)")
def remove(wid: str = Path(max_length=40), db: Session = Depends(db_session),
           key: ApiKey = Depends(require_api_key)):  # fmt: skip
    w = _get(db, key, wid)
    db.execute(delete(WatchlistCompany).where(WatchlistCompany.watchlist_id == w.id))
    db.delete(w)
    db.commit()
    return Response(status_code=204)


def _metric_cell(db: Session, cik: str, metric: str, as_of: date | None) -> dict | None:
    rows = intel.annual_series(db, cik, metric, as_of)
    if not rows:
        return None
    f, prev = rows[0], (rows[1] if len(rows) > 1 else None)
    cell = {"value": float(f.value), "unit": f.unit, "period_end": f.period_end.isoformat(),
            "form_type": f.form_type, "filed_date": f.filed_date.isoformat() if f.filed_date
            else None, "accession_number": f.accession_number, "source_url": f.source_url,
            "source_tag": f.source_tag, "mapping_version": f.mapping_version,
            "quality_status": f.quality_status, "derived": False, "yoy": None}  # fmt: skip
    if prev is not None and prev.value and prev.unit == f.unit:
        cell["yoy"] = {"value_pct": round((float(f.value) - float(prev.value))
                                          / abs(float(prev.value)) * 100, 1),
                       "derived": True,
                       "inputs": [{"period_end": x.period_end.isoformat(),
                                   "accession_number": x.accession_number,
                                   "source_url": x.source_url} for x in (prev, f)]}  # fmt: skip
    return cell


def _ratio_cell(db: Session, cik: str, name: str, as_of: date | None) -> dict | None:
    r = ratios.RATIOS[name]
    num = intel.annual_series(db, cik, r.numerator, as_of)
    den = intel.annual_series(db, cik, r.denominator, as_of)
    if not num or not den or num[0].period_end != den[0].period_end:
        return None
    if not ratios.compatible(r, num[0].unit, den[0].unit):
        return None
    value = ratios.compute(r, float(num[0].value), float(den[0].value))
    if value is None:
        return None
    return {"value": value, "unit": ratios.unit_of(r, num[0].unit),
            "period_end": num[0].period_end.isoformat(), "derived": True, "formula": r.formula,
            "inputs": [{"metric": x.metric, "accession_number": x.accession_number,
                        "source_url": x.source_url} for x in (num[0], den[0])]}  # fmt: skip


def _row(db: Session, c: Company, columns: list[str], as_of: date | None) -> dict:
    from app.db.models import MartCompany
    from app.services import thirteenf

    cells: dict = {}
    for col in columns:
        if col in SUPPORTED_METRICS:
            cells[col] = _metric_cell(db, c.cik, col, as_of)
        elif col in DERIVED:
            cells[col] = _ratio_cell(db, c.cik, col, as_of)
        elif col == "reporting_currency":
            mart = db.get(MartCompany, c.cik)
            cells[col] = mart.reporting_currency if mart else None
        elif col == "latest_filing":
            q = select(Filing).where(Filing.cik == c.cik)
            if as_of:
                q = q.where(Filing.filing_date <= as_of)
            f = db.scalars(q.order_by(Filing.filing_date.desc(), Filing.accession_number.desc())
                           .limit(1)).first()  # fmt: skip
            cells[col] = ({"form_type": f.form_type, "filing_date": f.filing_date.isoformat(),
                           "filing_url": f.source_url} if f else None)  # fmt: skip
        elif col == "last_event":
            items = timeline.build(db, c, EVENT_KINDS, as_of=as_of)
            cells[col] = next((i for i in items if not i["upcoming"]), None)
        elif col == "holders_change":
            block = thirteenf.for_company(db, c, as_of, top=1)
            cells[col] = ({"quarter": block["quarter"], "holders_count": block["holders_count"],
                           "holders_change": block["holders_count_change"]}
                          if block else None)  # fmt: skip
    return {"cik": c.cik, "display_name": intel.display_name(c.legal_name, c.ticker,
                                                             c.registrant_name),
            "ticker": c.ticker, "cells": cells}  # fmt: skip


@router.get("/{wid}/rows", summary="One row per company with the list's columns")
def rows(wid: str = Path(max_length=40), as_of: date | None = Query(None),
         db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)):  # fmt: skip
    w = _get(db, key, wid)
    columns = json.loads(w.columns)
    ciks = _ciks(db, w)
    comps = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(ciks)))}
    return {"id": _public_id(w), "as_of": as_of.isoformat() if as_of else None,
            "columns": columns,
            "data": [_row(db, comps[c], columns, as_of) for c in ciks if c in comps],
            "notes": ["Figures are each company's latest annual report as filed, in its own "
                      "reporting currency; a missing value is null, never 0."]}  # fmt: skip


@router.get("/{wid}/events", summary="The timeline items of every company in the list")
def events(wid: str = Path(max_length=40), types: str | None = Query(None, max_length=200),
           from_: date | None = Query(None, alias="from"), to: date | None = Query(None),
           as_of: date | None = Query(None), limit: int = Query(50, ge=1, le=200),
           cursor: str | None = Query(None, max_length=100),
           db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)):  # fmt: skip
    w = _get(db, key, wid)
    kinds = tuple(t.strip() for t in types.split(",") if t.strip()) if types else timeline.TYPES
    unknown = [t for t in kinds if t not in timeline.TYPES]
    if unknown:
        raise APIError(422, "invalid_parameter", f"Unknown timeline type: {', '.join(unknown)}.")
    try:
        offset = timeline.decode_cursor(cursor)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cursor is not valid.") from exc
    ciks = _ciks(db, w)
    items = []
    for c in db.scalars(select(Company).where(Company.cik.in_(ciks))):
        name = intel.display_name(c.legal_name, c.ticker, c.registrant_name)
        items += [{**i, "cik": c.cik, "display_name": name}
                  for i in timeline.build(db, c, kinds, from_, to, as_of,
                                          need=offset + limit + 1)]  # fmt: skip
    items.sort(key=lambda i: (i["date"], i["id"]), reverse=True)
    page, more = items[offset : offset + limit], len(items) > offset + limit
    return {"id": _public_id(w), "as_of": as_of.isoformat() if as_of else None, "data": page,
            "meta": {"limit": limit, "has_more": more,
                     "next_cursor": timeline.encode_cursor(offset + limit) if more else None},
            "notes": timeline.NOTES}  # fmt: skip


@router.post("/{wid}/watch", status_code=201, summary="Watch every company in the list")
def watch(body: WatchIn, request: Request, wid: str = Path(max_length=40),
          db: Session = Depends(db_session), settings: Settings = Depends(settings_dep),
          key: ApiKey = Depends(require_api_key)):  # fmt: skip
    """One existing company watch (/v1/watches) per company, with its signing, SSRF checks and
    plan limits. A webhook secret is shown once, per watch."""
    from app.api.routes_notifications import create_watch
    from app.schemas.watches import WatchCreate

    w = _get(db, key, wid)
    made = []
    for cik in _ciks(db, w):
        one = WatchCreate(cik=cik, destination_type=body.destination_type,
                          destination=body.destination, event_types=body.event_types)  # fmt: skip
        out = create_watch(one, request, db, settings, key)
        made.append({"cik": cik, "watch_id": str(out.id), "webhook_secret": out.webhook_secret})
    return {"id": _public_id(w), "watches": made}
