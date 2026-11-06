"""Officer changes within minutes of filing (ticket 20).

EDGAR's latest-filings feed (`browse-edgar?action=getcurrent&type=8-K&output=atom`) lists each new
8-K about two minutes after the SEC accepts it, with its item codes. Every
CURRENT_8K_POLL_SECONDS this job reads the feed once and, for each 8-K with item 5.02 not read
yet, loads the company's filings (without its XBRL facts), reads the 5.02 section and extracts
the changes with their evidence. They reach the event feed as `sec.officer_change` events.

SEC fair access: one feed request per poll (cached with ETag) plus two requests per new 5.02 filing
(the company's submissions and the 8-K document), well under ten a second.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Filing, FilingSection
from app.services import officer_changes
from app.services.form8k import LEADERSHIP_ITEM
from app.services.ingestion import ingest_company
from app.services.sec_client import SecClient, SecClientError

logger = logging.getLogger("app.jobs.current_8k")
FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb="
    "&owner=include&start=0&count=100&output=atom"
)
_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_FILER = re.compile(r"^(?P<form>\S+) - (?P<name>.*) \((?P<cik>\d{10})\) \((?P<role>[^)]*)\)$")
_ACCESSION = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
_ITEM = re.compile(r"Item (\d{1,2}\.\d{2})")
_UPDATED = re.compile(r"<updated>(.*?)</updated>")


@dataclass(frozen=True)
class CurrentFiling:
    cik: str
    company: str
    form: str
    accession_number: str
    items: tuple[str, ...]
    updated: datetime | None


def parse_feed(text: str) -> list[CurrentFiling]:
    """Entries of the latest-filings Atom feed; filer entries only (not reporting owners)."""
    out: list[CurrentFiling] = []
    for body in _ENTRY.findall(text):
        title = _TITLE.search(body)
        acc = _ACCESSION.search(body)
        if not title or not acc:
            continue
        m = _FILER.match(html.unescape(title.group(1)).strip())
        if not m or m.group("role") != "Filer":
            continue
        upd = _UPDATED.search(body)
        try:
            updated = datetime.fromisoformat(upd.group(1)) if upd else None
        except ValueError:
            updated = None
        out.append(
            CurrentFiling(
                cik=m.group("cik"),
                company=m.group("name"),
                form=m.group("form"),
                accession_number=acc.group(1),
                items=tuple(dict.fromkeys(_ITEM.findall(html.unescape(body)))),
                updated=updated,
            )
        )
    return out


def _already_read(db: Session, accession: str) -> bool:
    return (
        db.scalar(
            select(FilingSection.id).where(
                FilingSection.accession_number == accession,
                FilingSection.item == LEADERSHIP_ITEM,
            )
        )
        is not None
    )


def run_once(db: Session, settings: Settings, sec: SecClient, llm=None) -> dict:
    summary = {"entries": 0, "with_502": 0, "read": 0, "extracted": 0, "errors": 0}
    try:
        feed = sec.get_text(FEED_URL)
    except SecClientError as exc:
        log_event(logger, logging.WARNING, "current 8-K feed unavailable", error=str(exc))
        summary["errors"] += 1
        return summary
    entries = parse_feed(feed.data)
    summary["entries"] = len(entries)
    for entry in entries:
        if LEADERSHIP_ITEM not in entry.items or entry.form not in ("8-K", "8-K/A"):
            continue
        summary["with_502"] += 1
        if _already_read(db, entry.accession_number):
            continue
        filing = db.scalar(select(Filing).where(Filing.accession_number == entry.accession_number))
        if filing is None:
            try:
                ingest_company(db, sec, entry.cik, include_facts=False, history_pages=0)
            except SecClientError as exc:
                log_event(logger, logging.WARNING, "8-K filer ingest failed", cik=entry.cik,
                          error=str(exc))  # fmt: skip
                summary["errors"] += 1
                continue
            filing = db.scalar(
                select(Filing).where(Filing.accession_number == entry.accession_number)
            )
        if filing is None:  # not in the submissions yet; the next poll tries again
            continue
        done = officer_changes.ensure_extracted(db, [filing], sec=sec, llm=llm)
        summary["read"] += done["fetched"]
        summary["extracted"] += done["extracted"]
    log_event(logger, logging.INFO, "current 8-K poll", **summary)
    return summary


def run_forever(session_maker, settings: Settings) -> None:
    from app.services.llm import LocalLLM

    sec = SecClient(settings)
    llm = LocalLLM(settings) if settings.llm_enabled else None
    while True:
        db = session_maker()
        try:
            run_once(db, settings, sec, llm)
        except Exception:  # noqa: BLE001 - the loop must survive one bad poll
            logger.exception("current 8-K poll crashed")
            db.rollback()
        finally:
            db.close()
        time.sleep(settings.current_8k_poll_seconds)
