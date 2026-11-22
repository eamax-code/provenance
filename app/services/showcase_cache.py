"""Server-side cache for keyless (demo-key) showcase reads, kept until the data changes.

The showcase pages (overview, statements, timeline, insiders, 5% holders, ownership, the
screener) are read by every visitor with the same demo key, so a repeat view is served from
here: no database work, and it does not count against the demo limits (a hit returns before
the demo dependency runs). Only 200 responses to demo-key GETs are kept; a keyed request never
reads or writes this cache, because its answer can depend on the key's plan.

"Until the data changes": on PostgreSQL the version is the server's own write counters
(pg_stat_user_tables) summed over the data tables, read at most every RECHECK_SECONDS, so a
load, a mart refresh or an ingest empties the cache within that interval plus the server's
stats flush (about a second). Tables written on every request (counters, usage, sessions) are
left out, or every request would empty it. On other databases (tests) the version is fixed.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

from fastapi import Request
from sqlalchemy import text

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

_lock = threading.Lock()
_entries: OrderedDict[tuple, tuple[bytes, dict]] = OrderedDict()
_version: dict = {"value": None, "checked": 0.0}


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


def _read_version():
    from app.db.session import control_engine, get_engine

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return str(engine.url)
    names = ", ".join(f"'{t}'" for t in NOT_DATA)
    sql = (
        "SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables "
        f"WHERE relname NOT IN ({names})"
    )
    with control_engine().connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def data_version(now: float | None = None):
    now = time.monotonic() if now is None else now
    with _lock:
        if _version["value"] is not None and now - _version["checked"] < RECHECK_SECONDS:
            return _version["value"]
    value = _read_version()
    with _lock:
        if value != _version["value"]:
            _entries.clear()
        _version.update(value=value, checked=now)
    return value


def get(request: Request) -> tuple[bytes, dict] | None:
    version = data_version()
    with _lock:
        hit = _entries.get((version, *_key(request)))
        if hit is not None:
            _entries.move_to_end((version, *_key(request)))
        return hit


def put(request: Request, body: bytes, headers: dict) -> None:
    if len(body) > MAX_BODY_BYTES:
        return
    keep = {k: v for k, v in headers.items() if k.lower() not in ("content-length", "x-request-id")}
    version = data_version()
    with _lock:
        _entries[(version, *_key(request))] = (body, keep)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear() -> None:
    with _lock:
        _entries.clear()
        _version.update(value=None, checked=0.0)
