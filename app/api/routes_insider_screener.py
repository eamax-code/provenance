"""Q-03: the cross-company insider screener (docs/contracts/insider-screener.md). Open-market
buys and sales from stored Forms 4; information, not signals."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep
from app.api.routes_companies import _ERRORS, _parse_cik_param
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import Company, InsiderFiling
from app.services import insider_screener as scr
from app.services import insiders
from app.services.notes import detail, dev
from app.services.public import showcase_ciks
from app.services.response_cache import VersionedCache

CACHE = VersionedCache("/v1/insider-transactions")  # Q-03e
router = APIRouter(tags=["connections"])  # beside each company's insider-transactions
DEMO_ROWS = 10


@router.get(
    "/v1/insider-transactions",
    responses=_ERRORS,
    summary="Open-market insider buys and sales across companies (Form 4 codes P and S)",
    description="One row per Form 4, code and security class, lines added up (weighted "
    "average price). Amendments (4/A) never make a row; originals list them in amended_by, "
    "and show a 4/A's figures when it restates the row's lines (amended, first_filed). "
    "Filters on dates (at most 366 days), value, role, title, issuer, owner, the 10b5-1 box "
    "and F-03 cluster buying. Information, not signals. Not investment advice.",
)
def insider_screener(
    request: Request,
    type: str = Query("all", pattern="^(buy|sell|all)$"),  # noqa: A002 - the contract's name
    since: date | None = Query(None, description="Transactions on or after this date"),
    until: date | None = Query(None, description="Transactions on or before this date"),
    as_of: date | None = Query(None, description="Only Forms 4 filed by this date"),
    min_value: float | None = Query(None, ge=0, description="USD; rows without a value skipped"),
    max_value: float | None = Query(None, ge=0, description="USD; rows without a value skipped"),
    role: str | None = Query(
        None,
        max_length=80,
        description="director, officer, ten_percent_owner, other (comma-separated)",
    ),  # fmt: skip
    title: str | None = Query(
        None,
        max_length=250,
        description="Words in the officer title; "
        "comma-separated alternatives match any (ceo,chief executive)",
    ),
    cik: str | None = Query(None, max_length=13, description="One issuer"),
    owner_cik: str | None = Query(None, max_length=13, description="One reporting person"),
    plan_10b5_1: bool | None = Query(None, description="The Form 4's Rule 10b5-1 box"),
    cluster: bool | None = Query(None, description="true: only purchases in an F-03 cluster"),
    plan_purchase: bool | None = Query(
        None,
        description="F-03f: true, only purchases under an employee or director stock "
        "purchase plan, a plan trust or dividend reinvestment; false, none of them. Purchases "
        "(type=buy) leave them out unless set",
    ),  # fmt: skip
    sort: str = Query("date", pattern="^(date|value|filed)$"),
    limit: int = Query(50, ge=1, le=scr.MAX_LIMIT),
    offset: int = Query(0, ge=0, le=scr.MAX_OFFSET),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
) -> dict:
    until = until or as_of or date.today()
    if as_of and until > as_of:
        until = as_of
    since = since or until - timedelta(days=30)
    if since > until:
        raise APIError(422, "invalid_parameter", "since must be on or before until.")
    if (until - since).days > scr.MAX_DAYS:
        raise APIError(
            422, "invalid_parameter", f"At most {scr.MAX_DAYS} days from since to until."
        )
    roles = {r.strip().lower() for r in role.split(",") if r.strip()} if role else set()
    if not roles <= set(scr.ROLES):
        raise APIError(422, "invalid_parameter", "role must be among " + ", ".join(scr.ROLES) + ".")
    titles = [x.strip() for x in title.split(",") if x.strip()] if title is not None else []
    if title is not None and (not titles or len(titles) > 6 or any(len(x) > 40 for x in titles)):
        raise APIError(422, "invalid_parameter", "title takes 1-6 comma-separated alternatives "
                       "of up to 40 characters each.")  # fmt: skip
    if min_value is not None and max_value is not None and min_value > max_value:
        raise APIError(422, "invalid_parameter", "min_value is above max_value.")
    if cluster and type == "sell":
        raise APIError(422, "invalid_parameter", "cluster=true covers purchases only.")
    cik = _parse_cik_param(cik) if cik else None
    owner_cik = _parse_cik_param(owner_cik) if owner_cik else None
    allowed = set(showcase_ciks(db, settings)[0]) if getattr(request.state, "demo", False) else None
    if allowed is not None:
        if cik and cik not in allowed:
            raise APIError(403, "demo_scope",
                           "The demo key covers the public showcase companies only.")  # fmt: skip
        limit, offset = min(limit, DEMO_ROWS), 0
    codes = {scr.TYPES[type]} if type != "all" else set(scr.TYPES.values())
    s = scr.Screen(codes=codes, since=since, until=until, as_of=as_of, min_value=min_value,
                   max_value=max_value, roles=roles, titles=titles,
                   cik=cik, owner_cik=owner_cik, plan_10b5_1=plan_10b5_1,
                   plan_purchase=False if plan_purchase is None and type == "buy"
                   else plan_purchase,
                   cluster=bool(cluster), allowed=allowed)  # fmt: skip
    # Q-03e: a whole response is kept until the insider tables change (or 10 minutes pass);
    # the key is every parameter that shapes it, the demo scope included
    key = (type, since, until, as_of, min_value, max_value, tuple(sorted(roles)), tuple(titles),
           cik, owner_cik, plan_10b5_1, bool(cluster), plan_purchase, sort, limit, offset,
           tuple(sorted(allowed)) if allowed is not None else None)  # fmt: skip

    def build() -> dict:
        notes: list[str] = []
        if plan_purchase is None and type == "buy":
            notes.append("Purchases under an employee or director stock purchase plan, a plan "
                         "trust or dividend reinvestment are left out (plan_purchase=true lists "
                         "them): they are not open-market buys.")  # fmt: skip
        rows, counts = scr.screen(db, s)
        rows = scr.sort_rows(rows, sort)
        page, more = rows[offset : offset + limit], len(rows) > offset + limit
        scr.finish(db, page, s)
        if allowed is not None and more:
            more = False
            notes.append(f"The demo key shows at most {DEMO_ROWS} rows, from the showcase "
                         "companies; this list was trimmed.")  # fmt: skip
        companies = {c.cik: c for c in db.scalars(
            select(Company).where(Company.cik.in_({r["issuer_cik"] for r in page})))}  # fmt: skip
        datasets = insiders.dataset_coverage(db)
        # the newest Form 4 stored (the data sets, then Forms 4 read as filed for covered companies)
        through = db.scalar(select(func.max(InsiderFiling.filing_date))
                            .where(InsiderFiling.form_type == "4"))  # fmt: skip
        notes += [
            "Open-market purchases (Form 4 code P) and sales (code S) only, one row per Form 4, "
            "code and security class; grants, exercises, gifts, tax withholding and derivative "
            "rows are on each company's insider-transactions.",
            dev("Amendments (Form 4/A) never make a row: an original lists the 4/As for the same "
            "issuer, owner and period in amended_by. When a 4/A reports the row's code and class "
            "again with different figures (and at least as many lines), the row shows the 4/A's "
            "figures with amended: true, the 4/A as its filing, and the original's in first_filed; "
            "otherwise the figures are as first filed."
            + (f" {counts['restated']} row{'s' if counts['restated'] != 1 else ''} in this screen "
               "show a 4/A's figures." if counts["restated"] else "")
            + (f" {counts['unpaired_amendments']} amended filing"
               f"{'s' if counts['unpaired_amendments'] != 1 else ''} in this screen "
               "with no stored original Form 4 are not shown."
               if counts["unpaired_amendments"] else "")),
        ]  # fmt: skip
        if counts["duplicates"]:
            n = counts["duplicates"]
            notes.append(f"Shown once: {n} Form 4{'s' if n != 1 else ''} filed again the same day "
                         "with the same trades (listed in duplicate_filings).")  # fmt: skip
        if counts["filed_errors"]:
            n = counts["filed_errors"]
            notes.append(f"Left out as filed errors: {n} line{'s' if n != 1 else ''} dated "
                         "after the Form 4's own filing date or more than three years before "
                         "it.")  # fmt: skip
        if datasets and until > datasets:
            notes.append(f"The quarterly insider data sets run to {datasets.isoformat()}; later "
                         "Forms 4 are read as filed for companies covered here.")  # fmt: skip
        return {
            "data": [_out(r, companies.get(r["issuer_cik"])) for r in page],
            "meta": {"limit": limit, "offset": offset, "has_more": more,
                     "next_offset": offset + limit if more else None},
            "filters": {"type": type, "since": since, "until": until, "as_of": as_of},
            "through": through,
            "datasets_through": datasets,
            "labels": {"disclaimer": scr.DISCLAIMER},
            "notes": notes,
            "notes_detail": detail(notes),
        }  # fmt: skip

    return CACHE.get_or_build(key, build)


def _out(r: dict, c: Company | None) -> dict:
    from app.services.intel import display_name

    out = {k: v for k, v in r.items() if k not in ("issuer_cik", "period") and k[0] != "_"}
    out["issuer"] = {"cik": r["issuer_cik"],
                     "name": display_name(c.legal_name, c.ticker, c.registrant_name) if c else None,
                     "ticker": c.ticker if c else None}  # fmt: skip
    return {"issuer": out.pop("issuer"), **out}
