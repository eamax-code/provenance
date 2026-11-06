"""GLEIF issuer identity (CC0 data). Verified 2026-11-06: api.gleif.org JSON:API and the daily
ISIN-LEI mapping at mapping.gleif.org.

Issuers are resolved in batches: one API call returns up to BATCH LEI records
(filter[lei]=a,b,...), so a run of MARKETS_GLEIF_LOOKUPS_PER_RUN calls covers that many times
BATCH issuers. Listings whose register gives no issuer LEI get one from the ISIN-LEI mapping
(about 33 MB zipped, 9.4 million rows; downloaded once a day, streamed, size-capped). Records
older than MARKETS_GLEIF_REFRESH_DAYS are re-read so renames and lapsed registrations show.
The API's documented limit is 60 requests a minute; the client throttles itself.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Issuer, ListedInstrument, ListingEvent, utcnow
from app.services.markets.http import MarketFetchError, MarketHttp

logger = logging.getLogger("app.markets.gleif")
GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
GLEIF_SOURCE = "gleif"
ISIN_MAP_SOURCE = "gleif_isin_map"
ISIN_MAP_LATEST = "https://mapping.gleif.org/api/v2/isin-lei/latest"
ISIN_MAP_MAX_BYTES = 120 * 1024 * 1024
BATCH = 200


@dataclass(frozen=True)
class LeiRecord:
    lei: str
    legal_name: str
    country: str | None
    jurisdiction: str | None
    entity_status: str | None
    registration_status: str | None
    source_url: str


def parse_lei_record(payload: dict) -> LeiRecord | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        data = data[0] if data else None
    return _record(data)


def parse_lei_records(payload: dict) -> list[LeiRecord]:
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data if isinstance(data, list) else [data]
    return [r for r in (_record(d) for d in items) if r is not None]


def _record(data) -> LeiRecord | None:
    if not isinstance(data, dict):
        return None
    attrs = data.get("attributes", {})
    entity = attrs.get("entity", {})
    name = (entity.get("legalName") or {}).get("name")
    lei = attrs.get("lei") or data.get("id")
    if not lei or not name:
        return None
    return LeiRecord(
        lei=lei,
        legal_name=name,
        country=(entity.get("legalAddress") or {}).get("country"),
        jurisdiction=entity.get("jurisdiction"),
        entity_status=entity.get("status"),
        registration_status=(attrs.get("registration") or {}).get("status"),
        source_url=f"{GLEIF_API}/{lei}",
    )


def lookup_lei(http: MarketHttp, lei: str) -> LeiRecord | None:
    try:
        payload = http.get_json(f"{GLEIF_API}/{lei}")
    except MarketFetchError:
        return None
    return parse_lei_record(payload)


def lookup_by_isin(http: MarketHttp, isin: str) -> LeiRecord | None:
    try:
        payload = http.get_json(GLEIF_API, params={"filter[isin]": isin, "page[size]": 1})
    except MarketFetchError:
        return None
    return parse_lei_record(payload)


def lookup_leis(http: MarketHttp, leis: list[str]) -> dict[str, LeiRecord]:
    """Up to BATCH LEI records in one call; missing LEIs are simply absent."""
    if not leis:
        return {}
    try:
        payload = http.get_json(
            GLEIF_API, params={"filter[lei]": ",".join(leis[:BATCH]), "page[size]": BATCH}
        )
    except MarketFetchError:
        return {}
    return {r.lei: r for r in parse_lei_records(payload)}


def _apply(db: Session, issuer: Issuer, rec: LeiRecord, now: datetime) -> None:
    issuer.legal_name = rec.legal_name
    issuer.country = rec.country
    issuer.jurisdiction = rec.jurisdiction
    issuer.registration_status = rec.registration_status
    issuer.source = GLEIF_SOURCE
    issuer.source_url = rec.source_url
    issuer.updated_at = now
    # Instruments, and their events, keep the issuer's legal name once it is authoritative.
    ids = []
    for row in db.scalars(
        select(ListedInstrument).where(ListedInstrument.issuer_lei == issuer.lei)
    ):
        row.issuer_name = rec.legal_name
        ids.append(row.id)
    if ids:
        db.execute(
            update(ListingEvent)
            .where(ListingEvent.instrument_id.in_(ids))
            .values(issuer_name=rec.legal_name)
        )


def enrich_issuers(
    db: Session,
    settings: Settings,
    http: MarketHttp,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Fill issuer identity from GLEIF: first issuers with an LEI but no GLEIF record yet, then
    GLEIF records older than the refresh window. `limit` counts API calls of BATCH LEIs each."""
    now = now or utcnow()
    calls = settings.markets_gleif_lookups_per_run if limit is None else limit
    stale_before = now - timedelta(days=settings.markets_gleif_refresh_days)
    summary = {"calls": 0, "looked_up": 0, "enriched": 0, "refreshed": 0, "not_found": 0}
    for refreshing in (False, True):
        cond = (
            (Issuer.source == GLEIF_SOURCE) & (Issuer.updated_at < stale_before)
            if refreshing
            else (Issuer.source != GLEIF_SOURCE)
        )
        while summary["calls"] < calls:
            batch = db.scalars(
                select(Issuer)
                .where(Issuer.lei.is_not(None), cond)
                .order_by(Issuer.first_detected_at.desc(), Issuer.lei)
                .limit(BATCH)
            ).all()
            if not batch:
                break
            found = lookup_leis(http, [i.lei for i in batch])
            summary["calls"] += 1
            summary["looked_up"] += len(batch)
            for issuer in batch:
                rec = found.get(issuer.lei)
                if rec is None:
                    summary["not_found"] += 1
                    # Leave it for the next run, but behind the ones not tried yet.
                    issuer.first_detected_at = min(issuer.first_detected_at, stale_before)
                    if refreshing:
                        issuer.updated_at = now
                    continue
                _apply(db, issuer, rec, now)
                summary["refreshed" if refreshing else "enriched"] += 1
            db.commit()
            if len(batch) < BATCH or (not found and not refreshing):
                break
    log_event(logger, logging.INFO, "gleif enrichment", **summary)
    return summary


def map_isins(
    db: Session, settings: Settings, http: MarketHttp, now: datetime | None = None
) -> dict:
    """Give listings without an issuer LEI the one GLEIF's ISIN-LEI mapping names, creating the
    issuer (to be filled by enrich_issuers) when it is new."""
    now = now or utcnow()
    missing = {
        isin
        for isin in db.scalars(
            select(ListedInstrument.isin).where(
                ListedInstrument.issuer_lei.is_(None), ListedInstrument.isin.is_not(None)
            )
        )
    }
    summary = {"isins_without_lei": len(missing), "mapped": 0, "new_issuers": 0}
    if not missing:
        return summary
    try:
        meta = http.get_json(ISIN_MAP_LATEST)
        attrs = meta["data"]["attributes"]
        link, name = attrs["downloadLink"], attrs["fileName"]
    except (MarketFetchError, KeyError, TypeError):
        summary["error"] = "mapping metadata unavailable"
        return summary
    # The same connection and throttle, with room for the mapping file.
    big = MarketHttp(
        settings,
        http=http.http,
        cache_dir=http.cache_dir,
        max_bytes=ISIN_MAP_MAX_BYTES,
        sleep=http._sleep,
    )
    try:
        fetched = big.download(link, cache_key=f"gleif-isin-lei/{name}")
    except MarketFetchError as exc:
        summary["error"] = str(exc)
        return summary
    finally:
        big.close()
    found = read_isin_map(fetched.path, missing)
    for isin, lei in found.items():
        for row in db.scalars(
            select(ListedInstrument).where(
                ListedInstrument.isin == isin, ListedInstrument.issuer_lei.is_(None)
            )
        ):
            row.issuer_lei = lei
            summary["mapped"] += 1
            if db.scalar(select(Issuer.id).where(Issuer.lei == lei)) is None:
                db.add(
                    Issuer(
                        lei=lei,
                        legal_name=row.issuer_name,
                        source=ISIN_MAP_SOURCE,
                        first_detected_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
                summary["new_issuers"] += 1
    db.commit()
    log_event(logger, logging.INFO, "gleif isin mapping", **summary)
    return summary


def read_isin_map(path, wanted: set[str]) -> dict[str, str]:
    """ISIN -> LEI for the wanted ISINs, streamed from the mapping zip (LEI,ISIN rows)."""
    out: dict[str, str] = {}
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(member) as raw:
            for row in csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                if len(row) >= 2 and row[1] in wanted:
                    out[row[1]] = row[0]
    return out
