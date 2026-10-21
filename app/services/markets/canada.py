"""Canadian exchange-direct adapters: TSX/TSXV company directory and CSE listed companies.

Both feeds are machine-readable JSON with no key, verified 2026-10-22, but their site terms
restrict use to personal/non-commercial purposes and forbid redistribution without written
permission (tsx.com/en/terms-of-use; thecse.com site terms). They are therefore DISABLED by
default: enabling `tsx` or `cse` in MARKETS_SOURCES_ENABLED is the operator's statement that
they hold the required permission. Neither feed carries ISINs; rows are keyed by symbol.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import utcnow
from app.services.ingestion import finish_run, start_run
from app.services.markets.http import MarketFetchError, MarketHttp
from app.services.markets.ingest import MarketIngestResult, ingest_records
from app.services.markets.records import (
    STATUS_DELISTED,
    STATUS_LISTED,
    STATUS_SUSPENDED,
    ListingRecord,
)
from app.services.markets.venues import seed_venues

logger = logging.getLogger("app.markets.canada")

TSX_SOURCE = "tsx"
CSE_SOURCE = "cse"
TSX_BASE = "https://www.tsx.com/json/company-directory"
TSX_MICS = {"tsx": "XTSE", "tsxv": "XTSX"}
CSE_LISTED_URL = "https://thecse.com/api/webapi/listed-companies/"
CSE_MIC = "XCNQ"


def _epoch_date(value) -> date | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).date() if value else None
    except (TypeError, ValueError, OSError):
        return None


def _results(payload) -> list[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [r for r in payload["results"] if isinstance(r, dict)]
    return []


# ---- TSX / TSXV ----------------------------------------------------------------------------


def parse_tsx(
    exchange: str,
    directory: dict,
    recent: dict | None = None,
    delisted: dict | None = None,
    suspended: dict | None = None,
) -> list[ListingRecord]:
    """Combine the directory with the recent/delisted/suspended lists into listing records."""
    mic = TSX_MICS[exchange]
    base_url = f"{TSX_BASE}/search/{exchange}/^*"
    recent_dates = {
        r["symbol"]: _epoch_date(r.get("date")) for r in _results(recent) if r.get("symbol")
    }
    suspended_syms = {r["symbol"] for r in _results(suspended) if r.get("symbol")}
    out: dict[str, ListingRecord] = {}
    for r in _results(directory):
        sym, name = r.get("symbol"), r.get("name")
        if not sym or not name:
            continue
        status = STATUS_SUSPENDED if sym in suspended_syms else STATUS_LISTED
        out[sym] = ListingRecord(
            mic=mic,
            symbol=sym,
            issuer_name=name,
            source=TSX_SOURCE,
            source_url=base_url,
            instrument_type="listing",
            currency="CAD",
            first_trade_date=recent_dates.get(sym),
            status=status,
            quality_status="partial",
            notes=[
                "TSX directory carries no ISIN, CUSIP or LEI; keyed by symbol",
                "instrument_type unknown from source (equities, ETFs and CDRs share the directory)",
            ],
        )
    for r in _results(delisted):
        sym, name = r.get("symbol"), r.get("name")
        if not sym or not name:
            continue
        out[sym] = ListingRecord(
            mic=mic,
            symbol=sym,
            issuer_name=name,
            source=TSX_SOURCE,
            source_url=f"{TSX_BASE}/delisted/{exchange}",
            instrument_type="listing",
            currency="CAD",
            termination_date=_epoch_date(r.get("date")),
            status=STATUS_DELISTED,
            quality_status="partial",
            notes=["delisting reported by the TSX delisted list; reason not provided"],
        )
    return list(out.values())


def fetch_tsx(http: MarketHttp, exchange: str) -> list[ListingRecord]:
    directory = http.get_json(f"{TSX_BASE}/search/{exchange}/^*")
    extras = {}
    for kind in ("recent", "delisted", "suspended"):
        try:
            extras[kind] = http.get_json(f"{TSX_BASE}/{kind}/{exchange}")
        except MarketFetchError as exc:
            log_event(logger, logging.WARNING, "tsx list unavailable", kind=kind, error=str(exc))
            extras[kind] = None
    return parse_tsx(exchange, directory, extras["recent"], extras["delisted"], extras["suspended"])


# ---- CSE ------------------------------------------------------------------------------------

CSE_STATUS = {
    "active": STATUS_LISTED,
    "suspended": STATUS_SUSPENDED,
    "halted pending fundamental change": STATUS_SUSPENDED,
    "delisted": STATUS_DELISTED,
}


def parse_cse(payload, equity_only: bool = True) -> list[ListingRecord]:
    rows = payload if isinstance(payload, list) else []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym, name = r.get("symbol"), r.get("security_name")
        if not sym or not name:
            continue
        if equity_only and (r.get("security_type") or "").lower() != "equity":
            continue
        status = CSE_STATUS.get((r.get("status") or "").lower())
        notes = ["CSE feed carries no ISIN or LEI; keyed by symbol"]
        if r.get("status") and status == STATUS_SUSPENDED and "halt" in r["status"].lower():
            notes.append(f"source status: {r['status']}")
        change = r.get("recent_change") or {}
        if change.get("type"):
            notes.append(f"recent change ({change.get('effective_on')}): {change.get('type')}")
        out.append(
            ListingRecord(
                mic=CSE_MIC,
                symbol=sym,
                issuer_name=name,
                source=CSE_SOURCE,
                source_url=CSE_LISTED_URL,
                instrument_type="share",
                currency=r.get("currency") or "CAD",
                first_trade_date=_iso_date(r.get("listing_date")),
                status=status or STATUS_LISTED,
                quality_status="partial" if status is None else "ok",
                notes=notes
                + ([f"unmapped source status {r.get('status')!r}"] if status is None else []),
            )
        )
    return out


def _iso_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# ---- runners -------------------------------------------------------------------------------


def ingest_source(
    db: Session, settings: Settings, http: MarketHttp, source: str, now: datetime | None = None
) -> dict:
    """Run one Canadian adapter end to end. Caller checks the source is enabled."""
    now = now or utcnow()
    run = start_run(db, source=f"markets:{source}")
    db.commit()
    markets = seed_venues(db, source=source)
    db.commit()
    summary: dict = {
        "source": source,
        "records": 0,
        "inserted": 0,
        "updated": 0,
        "events": {},
        "errors": [],
    }
    try:
        if source == TSX_SOURCE:
            records = fetch_tsx(http, "tsx") + fetch_tsx(http, "tsxv")
        elif source == CSE_SOURCE:
            records = parse_cse(http.get_json(CSE_LISTED_URL))
        else:
            raise ValueError(f"unknown Canadian source {source}")
        res: MarketIngestResult = ingest_records(
            db, records, source, now=now, known_markets=markets
        )
        summary.update(
            records=res.records_seen, inserted=res.inserted, updated=res.updated, events=res.events
        )
        run = db.merge(run)
        run.inserted_count += res.inserted
        run.updated_count += res.updated
        finish_run(db, run, "succeeded")
    except MarketFetchError as exc:
        db.rollback()
        run = db.merge(run)
        run.error_count += 1
        finish_run(db, run, "failed", str(exc))
        summary["errors"].append(str(exc))
    db.commit()
    return summary
