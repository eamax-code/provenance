"""Server-side cache for keyless (demo-key) showcase reads, kept until the data changes.

The showcase pages (overview, statements, timeline, insiders, 5% holders, ownership, the
screener) are read by every visitor with the same demo key, so a repeat view is served from
here: no database work, and it does not count against the demo limits (a hit returns before
the demo dependency runs). Only 200 responses to demo-key GETs are kept; a keyed request never
reads or writes this cache, because its answer can depend on the key's plan.

"Until the data changes": on PostgreSQL the version is the server's own write counters
(pg_stat_user_tables), read at most every RECHECK_SECONDS and summed per page over the tables
that page reads (C-11, GROUPS; all data tables for the overview), so a load into those tables
retires the page within that interval plus the server's stats flush (about a second), and a
load elsewhere leaves it cached. Tables written on every request (counters, usage, sessions) are
left out, or every request would empty it. On other databases (tests) the version is fixed.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

from fastapi import Request
from sqlalchemy import text

from app.core.single_flight import AsyncSingleFlight

PATHS = re.compile(
    r"^/v1/(?:companies/[^/]+/(?:overview|statements/[a-z_]+|timeline|insiders"
    r"|insider-transactions|holders|ownership)|facts/screen)$"
)
RECHECK_SECONDS = 30
MAX_ENTRIES = 2000
MAX_BODY_BYTES = 512_000
NOT_DATA = (
    "rate_limit_counters", "api_usage", "audit_events", "chat_messages", "chat_sessions",
    "sign_in_tokens", "account_sessions", "accounts", "api_keys", "key_requests", "watchlists",
    "watchlist_companies", "company_watches", "listing_watches", "type_watches",
    "notification_deliveries", "alembic_version",
)  # fmt: skip
DEMO_KEY = "demo"
# C-11: each page's version counts only the tables it reads, so a load elsewhere (segment labels,
# comment letters, Form 144) keeps its pages cached. A page not listed reads everything.
_PEOPLE = ("companies", "company_aliases", "registrant_successions", "mart_company")
GROUPS = {
    "statements": _PEOPLE + ("financial_facts", "mart_company_period", "mart_financials",
                             "filings", "filing_statement_tags", "fx_rates"),
    "timeline": _PEOPLE + ("filings", "dated_events", "insider_activity", "officer_changes",
                           "filings_13f", "holdings_13f", "issuer_cusips", "form144_notices",
                           "trading_plans", "filing_sections"),
    "insiders": _PEOPLE + ("insider_filings", "insider_transactions", "insider_activity",
                           "officer_changes"),
    "holders": _PEOPLE + ("beneficial_owners", "filings"),
    "ownership": _PEOPLE + ("filings_13f", "holdings_13f", "issuer_cusips"),
    "screen": _PEOPLE + ("financial_facts", "mart_company_period", "mart_financials",
                         "fx_rates"),
}  # fmt: skip
_PAGE_GROUP = (
    (re.compile(r"/statements/"), "statements"), (re.compile(r"/timeline$"), "timeline"),
    (re.compile(r"/insider(s|-transactions)$"), "insiders"), (re.compile(r"/holders$"), "holders"),
    (re.compile(r"/ownership$"), "ownership"), (re.compile(r"^/v1/facts/screen$"), "screen"),
)  # fmt: skip

_lock = threading.Lock()
_entries: OrderedDict[tuple, tuple[bytes, dict]] = OrderedDict()
_version: dict = {"value": None, "checked": 0.0}  # value: {table: writes}


def group_for(path: str) -> str | None:
    return next((g for rx, g in _PAGE_GROUP if rx.search(path)), None)
_flight = AsyncSingleFlight()  # concurrent misses for one page compute once


def is_demo_read(request: Request) -> bool:
    if request.method != "GET" or not PATHS.match(request.url.path):
        return False
    header = request.headers.get("x-api-key")
    if header is not None:
        return header == DEMO_KEY
    return request.query_params.get("api_key") == DEMO_KEY


def _key(request: Request) -> tuple:
    params = sorted((k, v) for k, v in request.query_params.multi_items() if k != "api_key")
    return request.url.path, tuple(params)


def _read_version() -> dict:
    """Writes per data table (pg_stat_user_tables), or a fixed map on other databases."""
    from app.db.session import control_engine, get_engine

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return {"*": str(engine.url)}
    names = ", ".join(f"'{t}'" for t in NOT_DATA)
    sql = (
        "SELECT relname, n_tup_ins + n_tup_upd + n_tup_del FROM pg_stat_user_tables "
        f"WHERE relname NOT IN ({names})"
    )
    with control_engine().connect() as conn:
        return {r: int(n) for r, n in conn.execute(text(sql)).all()}


def _counts(now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    with _lock:
        if _version["value"] is not None and now - _version["checked"] < RECHECK_SECONDS:
            return _version["value"]
    value = _read_version()
    with _lock:
        _version.update(value=value, checked=now)
    return value


def data_version(now: float | None = None, path: str | None = None):
    """The version of the data a page reads: the writes to its group's tables (all data tables
    for a page with no group). Entries of an older version are never served and age out of the
    LRU."""
    counts = _counts(now)
    group = group_for(path) if path else None
    tables = GROUPS.get(group) if group else None
    if tables is None:
        return ("*", sum(v for v in counts.values() if isinstance(v, int)) if "*" not in counts
                else counts["*"])  # fmt: skip
    return (group, sum(counts.get(t, 0) for t in tables))


def get(request: Request) -> tuple[bytes, dict] | None:
    version = data_version(path=request.url.path)
    with _lock:
        hit = _entries.get((version, *_key(request)))
        if hit is not None:
            _entries.move_to_end((version, *_key(request)))
        return hit


def put(request: Request, body: bytes, headers: dict) -> None:
    if len(body) > MAX_BODY_BYTES:
        return
    keep = {k: v for k, v in headers.items() if k.lower() not in ("content-length", "x-request-id")}
    version = data_version(path=request.url.path)
    with _lock:
        _entries[(version, *_key(request))] = (body, keep)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


async def lead_or_wait(request: Request) -> bool:
    """On a miss: True when this request computes the page (it must call finish); False after
    waiting for the request already computing it (read the cache again)."""
    key = (data_version(path=request.url.path), *_key(request))
    request.state.showcase_key = key
    leader, event = _flight.acquire(key)
    if not leader:
        await _flight.wait(event)
    return leader


def finish(request: Request) -> None:
    _flight.release(request.state.showcase_key)


def clear() -> None:
    with _lock:
        _entries.clear()
        _version.update(value=None, checked=0.0)
