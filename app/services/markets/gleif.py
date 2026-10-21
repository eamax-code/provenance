"""GLEIF LEI lookups (CC0 data) for issuer identity. Verified 2026-10-22: api.gleif.org JSON:API.

Rate limit is documented at 60 requests/minute; the client throttles itself and lookups per
run are bounded by MARKETS_GLEIF_LOOKUPS_PER_RUN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Issuer, ListedInstrument, utcnow
from app.services.markets.http import MarketFetchError, MarketHttp

logger = logging.getLogger("app.markets.gleif")
GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
GLEIF_SOURCE = "gleif"


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


def enrich_issuers(
    db: Session,
    settings: Settings,
    http: MarketHttp,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Fill issuer identity from GLEIF for issuers that have an LEI but no GLEIF record yet."""
    now = now or utcnow()
    limit = settings.markets_gleif_lookups_per_run if limit is None else limit
    pending = db.scalars(
        select(Issuer)
        .where(Issuer.lei.is_not(None), Issuer.source != GLEIF_SOURCE)
        .order_by(Issuer.first_detected_at.desc())
        .limit(limit)
    ).all()
    summary = {"looked_up": 0, "enriched": 0, "not_found": 0}
    for issuer in pending:
        summary["looked_up"] += 1
        rec = lookup_lei(http, issuer.lei)
        if rec is None:
            summary["not_found"] += 1
            continue
        issuer.legal_name = rec.legal_name
        issuer.country = rec.country
        issuer.jurisdiction = rec.jurisdiction
        issuer.registration_status = rec.registration_status
        issuer.source = GLEIF_SOURCE
        issuer.source_url = rec.source_url
        issuer.updated_at = now
        # Instruments keep the issuer's legal name once it is authoritative.
        for row in db.scalars(
            select(ListedInstrument).where(ListedInstrument.issuer_lei == issuer.lei)
        ):
            row.issuer_name = rec.legal_name
        summary["enriched"] += 1
    db.commit()
    log_event(logger, logging.INFO, "gleif enrichment", **summary)
    return summary
