"""ESMA and FCA FIRDS adapters: file discovery, streaming XML parsing, bounded ingestion.

Verified 2026-10-22 against live registers and DLTINS_20261021_01of04 (see
docs/research/international-listings-sources.md):
- ESMA register: Solr JSON at registers.esma.europa.eu; files at firds.esma.europa.eu/firds/.
- FCA register: Elasticsearch JSON at api.data.fca.org.uk; files under
  data.fca.org.uk/artefacts/FIRDS/.
- Delta files (auth.036): FinInstrmRptgRefDataDltaRpt/FinInstrm/{NewRcrd|ModfdRcrd|
  TermntdRcrd|CancRcrd}. Full files (auth.017): FinInstrmRptgRefDataRpt/RefData.
Attribution: ESMA and FCA are the sources; this service is not endorsed by either.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import IngestionRun, MarketSourceFile, utcnow
from app.services.ingestion import finish_run, start_run
from app.services.markets.http import MarketFetchError, MarketHttp
from app.services.markets.ingest import MarketIngestResult, ingest_records
from app.services.markets.records import STATUS_DELISTED, STATUS_LISTED, ListingRecord
from app.services.markets.venues import seed_venues

logger = logging.getLogger("app.markets.firds")

ESMA_REGISTER_URL = "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
FCA_REGISTER_URL = "https://api.data.fca.org.uk/fca_data_firds_files"
ESMA_SOURCE = "esma_firds"
FCA_SOURCE = "fca_firds"
OPEN_ENDED = date(9999, 12, 31)
RECORD_TAGS = {
    "NewRcrd": "new",
    "ModfdRcrd": "modified",
    "TermntdRcrd": "terminated",
    "CancRcrd": "cancelled",
    "RefData": "full",
}
EQUITY_CFI_PREFIXES = ("ES", "EP")  # shares and preferred shares; funds (EU), rights etc. excluded


@dataclass(frozen=True)
class FirdsFile:
    source: str
    file_name: str
    file_type: str  # FULINS | DLTINS | FULCAN
    publication_date: datetime | None
    download_link: str


# ---- discovery -----------------------------------------------------------------------------


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(text[:10]), datetime.min.time(), tzinfo=UTC)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def list_esma_files(
    http: MarketHttp, since: date, until: date, file_types=("DLTINS",)
) -> list[FirdsFile]:
    params = {
        "q": "*",
        "fq": f"publication_date:[{since.isoformat()}T00:00:00Z TO {until.isoformat()}T23:59:59Z]",
        "wt": "json",
        "start": 0,
        "rows": 500,
    }
    data = http.get_json(ESMA_REGISTER_URL, params=params)
    docs = (data or {}).get("response", {}).get("docs", []) if isinstance(data, dict) else []
    return _sorted(
        [
            FirdsFile(
                ESMA_SOURCE,
                d["file_name"],
                d.get("file_type", ""),
                _parse_dt(d.get("publication_date")),
                d["download_link"],
            )
            for d in docs
            if isinstance(d, dict)
            and d.get("file_name")
            and d.get("download_link")
            and d.get("file_type") in file_types
        ]
    )


def list_fca_files(
    http: MarketHttp, since: date, until: date, file_types=("DLTINS",)
) -> list[FirdsFile]:
    types = " OR ".join(f"file_type:{t}" for t in file_types)
    params = {
        "q": f"(({types}) AND (publication_date:[{since.isoformat()} TO {until.isoformat()}]))",
        "from": 0,
        "size": 500,
        "sort": "publication_date:asc",
    }
    data = http.get_json(FCA_REGISTER_URL, params=params)
    hits = (data or {}).get("hits", {}).get("hits", []) if isinstance(data, dict) else []
    out = []
    for h in hits:
        src = h.get("_source", {}) if isinstance(h, dict) else {}
        if src.get("file_name") and src.get("download_link") and src.get("file_type") in file_types:
            out.append(
                FirdsFile(
                    FCA_SOURCE,
                    src["file_name"],
                    src["file_type"],
                    _parse_dt(src.get("publication_date")),
                    src["download_link"],
                )
            )
    return _sorted(out)


def _relevant(f: FirdsFile) -> bool:
    """Full files are split by CFI first letter (FULINS_<letter>_...); only equities (E) matter."""
    if f.file_type == "FULINS":
        return f.file_name.upper().startswith("FULINS_E_")
    return True


def _sorted(files: list[FirdsFile]) -> list[FirdsFile]:
    files = [f for f in files if _relevant(f)]
    return sorted(
        files, key=lambda f: (f.publication_date or datetime.min.replace(tzinfo=UTC), f.file_name)
    )


# ---- parsing -------------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(el: ET.Element, path: list[str]) -> str | None:
    cur: ET.Element | None = el
    for name in path:
        if cur is None:
            return None
        cur = next((c for c in cur if _local(c.tag) == name), None)
    return cur.text.strip() if cur is not None and cur.text else None


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


@dataclass
class ParsedFirdsRecord:
    kind: str  # new | modified | terminated | cancelled | full
    record: ListingRecord


def parse_firds_xml(
    stream,
    source: str,
    source_url: str,
    covered_mics: set[str],
    cfi_prefixes: tuple[str, ...] = EQUITY_CFI_PREFIXES,
    published_at: datetime | None = None,
) -> Iterator[ParsedFirdsRecord]:
    """Stream records from a FIRDS XML file object, yielding only covered venues and equity CFIs."""
    for _event, el in ET.iterparse(stream, events=("end",)):
        tag = _local(el.tag)
        if tag not in RECORD_TAGS:
            if tag == "FinInstrm":
                el.clear()
            continue
        kind = RECORD_TAGS[tag]
        mic = _find_text(el, ["TradgVnRltdAttrbts", "Id"])
        cfi = _find_text(el, ["FinInstrmGnlAttrbts", "ClssfctnTp"]) or ""
        if mic in covered_mics and cfi.startswith(cfi_prefixes):
            isin = _find_text(el, ["FinInstrmGnlAttrbts", "Id"])
            term = _to_date(_find_text(el, ["TradgVnRltdAttrbts", "TermntnDt"]))
            if term == OPEN_ENDED:
                term = None
            first = _to_date(_find_text(el, ["TradgVnRltdAttrbts", "FrstTradDt"]))
            pub = _to_date(_find_text(el, ["TechAttrbts", "PblctnPrd", "FrDt"]))
            if kind == "terminated" and term is None:
                term = pub  # ESMA: a terminated record without a date ceases at publication
            status = STATUS_DELISTED if (kind == "terminated") else None
            if (
                status is None
                and term is not None
                and term <= (published_at.date() if published_at else date.today())
            ):
                status = STATUS_DELISTED
            notes = [f"firds:{kind}"]
            if kind == "cancelled":
                notes.append("record cancelled by the source; treated as not listed")
                status = STATUS_DELISTED
            rec = ListingRecord(
                isin=isin,
                mic=mic,
                issuer_name=_find_text(el, ["FinInstrmGnlAttrbts", "FullNm"]) or "",
                short_name=_find_text(el, ["FinInstrmGnlAttrbts", "ShrtNm"]),
                issuer_lei=_find_text(el, ["Issr"]),
                cfi_code=cfi[:6],
                instrument_type="preferred_share" if cfi.startswith("EP") else "share",
                currency=_find_text(el, ["FinInstrmGnlAttrbts", "NtnlCcy"]),
                admission_requested_date=_to_date(
                    _find_text(el, ["TradgVnRltdAttrbts", "ReqForAdmssnDt"])
                ),
                admission_approved_date=_to_date(
                    _find_text(el, ["TradgVnRltdAttrbts", "AdmssnApprvlDtByIssr"])
                ),
                first_trade_date=first,
                termination_date=term,
                status=status if status else STATUS_LISTED,
                source=source,
                source_url=source_url,
                source_published_at=published_at,
                quality_status="ok" if (isin and first) else "partial",
                notes=notes,
            )
            if not rec.issuer_name:
                rec.notes.append("instrument full name missing")
            rec.notes.append("issuer_name is the instrument full name until GLEIF enrichment")
            yield ParsedFirdsRecord(kind, rec)
        el.clear()


def parse_firds_zip(
    path: Path, source: str, source_url: str, covered_mics: set[str], published_at=None
) -> Iterator[ParsedFirdsRecord]:
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".xml"):
                continue
            with zf.open(name) as stream:
                yield from parse_firds_xml(
                    stream, source, source_url, covered_mics, published_at=published_at
                )


# ---- ingestion -----------------------------------------------------------------------------


def _already_done(db: Session, source: str, file_name: str) -> bool:
    return (
        db.scalar(
            select(MarketSourceFile.id).where(
                MarketSourceFile.source == source,
                MarketSourceFile.file_name == file_name,
                MarketSourceFile.status == "done",
            )
        )
        is not None
    )


def ingest_firds_file(
    db: Session, settings: Settings, http: MarketHttp, f: FirdsFile, now: datetime | None = None
) -> MarketIngestResult:
    now = now or utcnow()
    markets = seed_venues(db, source=f.source)
    db.commit()
    covered = set(markets)
    fetched = http.download(f.download_link, cache_key=f"{f.source}:{f.file_name}")
    # Collapse multiple records for the same (key, MIC) within a file: the last one wins.
    latest: dict[tuple[str, str], ListingRecord] = {}
    seen = 0
    for parsed in parse_firds_zip(
        fetched.path, f.source, f.download_link, covered, published_at=f.publication_date
    ):
        seen += 1
        key = parsed.record.listing_key
        if key:
            latest[(key, parsed.record.mic)] = parsed.record
    result = ingest_records(db, list(latest.values()), f.source, now=now, known_markets=markets)
    result.records_seen = seen
    db.add(
        MarketSourceFile(
            source=f.source,
            file_name=f.file_name,
            file_type=f.file_type,
            source_url=f.download_link,
            published_at=f.publication_date,
            status="done",
            records_seen=seen,
            records_ingested=result.inserted + result.updated,
            processed_at=now,
        )
    )
    db.commit()
    return result


def ingest_firds(
    db: Session,
    settings: Settings,
    http: MarketHttp,
    source: str,
    days_back: int | None = None,
    now: datetime | None = None,
    file_types=("DLTINS",),
    max_files: int = 20,
) -> dict:
    """Discover and ingest the last N days of FIRDS files for one register. Skips files done."""
    now = now or utcnow()
    days = settings.markets_firds_days_back if days_back is None else days_back
    since, until = (now - timedelta(days=days)).date(), now.date()
    run = start_run(db, source=f"markets:{source}")
    db.commit()
    summary = {
        "source": source,
        "files_listed": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "records_seen": 0,
        "inserted": 0,
        "updated": 0,
        "events": {},
        "errors": [],
    }
    try:
        files = (
            list_esma_files(http, since, until, file_types)
            if source == ESMA_SOURCE
            else list_fca_files(http, since, until, file_types)
        )
    except MarketFetchError as exc:
        finish_run(db, run, "failed", str(exc))
        db.commit()
        summary["errors"].append(str(exc))
        return summary
    summary["files_listed"] = len(files)
    for f in files[-max_files:]:
        if _already_done(db, source, f.file_name):
            summary["files_skipped"] += 1
            continue
        try:
            res = ingest_firds_file(db, settings, http, f, now=now)
        except (MarketFetchError, zipfile.BadZipFile, ET.ParseError) as exc:
            db.rollback()
            db.add(
                MarketSourceFile(
                    source=source,
                    file_name=f.file_name,
                    file_type=f.file_type,
                    source_url=f.download_link,
                    published_at=f.publication_date,
                    status="failed",
                    error=str(exc)[:300],
                    processed_at=now,
                )
            )
            db.commit()
            summary["errors"].append(f"{f.file_name}: {type(exc).__name__}")
            run = db.merge(run)
            run.error_count += 1
            continue
        summary["files_processed"] += 1
        summary["records_seen"] += res.records_seen
        summary["inserted"] += res.inserted
        summary["updated"] += res.updated
        for k, v in res.events.items():
            summary["events"][k] = summary["events"].get(k, 0) + v
    run = db.merge(run)
    run.inserted_count += summary["inserted"]
    run.updated_count += summary["updated"]
    status = (
        "succeeded"
        if not summary["errors"]
        else ("failed" if summary["files_processed"] == 0 else "partial")
    )
    finish_run(db, run, status, "; ".join(summary["errors"])[:2000] or None)
    db.commit()
    log_event(
        logger, logging.INFO, "firds ingest", **{k: v for k, v in summary.items() if k != "errors"}
    )
    return summary


def _unused(_: IngestionRun) -> None:  # keep the import meaningful for type checkers
    return None
