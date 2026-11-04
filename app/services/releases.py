"""The company's latest earnings release: the press release filed as exhibit 99.1 to an 8-K
under item 2.02 (results of operations). Fetched once and stored like other filing text."""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Filing, FilingSection
from app.services.prospectus import to_text
from app.services.sec_client import SecClient, SecClientError

logger = logging.getLogger("app.releases")

EARNINGS_ITEM = "2.02"
ITEM = "ex:99.1"
MAX_CHARS = 60_000
_ROW = re.compile(r"(?is)<tr\b.*?</tr>")
_TD = re.compile(r"(?is)<td\b[^>]*>(.*?)</td>")
_HREF = re.compile(r'href="(/Archives/[^"]+)"')


def latest_release_filing(db: Session, cik: str, as_of: date | None = None) -> Filing | None:
    stmt = select(Filing).where(
        Filing.cik == cik, Filing.form_type.like("8-K%"), Filing.items.like(f"%{EARNINGS_ITEM}%")
    )
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    return db.scalars(
        stmt.order_by(Filing.filing_date.desc(), Filing.accession_number.desc()).limit(1)
    ).first()


def exhibit_url(index_html: str) -> str | None:
    """The press release in a filing index: the EX-99.1 row (or the first EX-99)."""
    found = []
    for row in _ROW.findall(index_html):
        cells = [re.sub(r"<[^>]+>|&nbsp;", " ", c).strip().upper() for c in _TD.findall(row)]
        href = _HREF.search(row)
        if href and any(c.startswith("EX-99") for c in cells):
            exact = any(c in ("EX-99.1", "EX-99.01") for c in cells)
            found.append((not exact, "https://www.sec.gov" + href.group(1)))
    return min(found)[1] if found else None


def stored(db: Session, accession_number: str) -> FilingSection | None:
    return db.scalar(
        select(FilingSection).where(
            FilingSection.accession_number == accession_number, FilingSection.item == ITEM
        )
    )


def ensure_read(db: Session, f: Filing, sec: SecClient | None) -> str:
    """Fetch the release once. Returns stored, not_read, read or failed."""
    if stored(db, f.accession_number) is not None:
        return "stored"
    if sec is None:
        return "not_read"
    row = FilingSection(
        cik=f.cik,
        accession_number=f.accession_number,
        item=ITEM,
        status="fetch_failed",
        source_url=f.source_url,
        fetched_at=datetime.now(UTC),
    )
    try:
        url = exhibit_url(sec.get_text(f.source_url).data)
        if url:
            text = to_text(sec.get_text(url).data)
            start = re.search(r"(?i)exhibit\s+99\.?0?1", text)
            row.text = text[start.start() if start else 0 :][:MAX_CHARS]
            row.status, row.source_url = "ok", url
        else:
            row.status = "no_section"
    except SecClientError as exc:
        log_event(logger, logging.WARNING, "release fetch failed", url=f.source_url, error=str(exc))
    db.add(row)
    db.commit()
    return "read" if row.status == "ok" else "failed"


def highlights(db: Session, f: Filing, limit: int = 3500) -> tuple[str, str] | None:
    """(text, url): the opening of the stored release, where the headline results are."""
    row = stored(db, f.accession_number)
    if row is None or row.status != "ok" or not row.text:
        return None
    return row.text[:limit], row.source_url
