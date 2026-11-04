"""News headlines for forecasts: the company and its industry, cached on disk.

Only the headline, publisher, date and link are used, never article text, and each headline is
cited. Headlines are untrusted data: they are shown to the model as data and never followed as
instructions. The default provider is Google News RSS, whose terms allow personal,
non-commercial use; a commercial deployment swaps in a licensed provider with `search()`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

import httpx

from app.core.config import Settings
from app.core.logging import log_event

logger = logging.getLogger("app.news")

MAX_TITLE = 200
BUSINESS_WORDS = "earnings OR revenue OR sales OR demand OR growth OR guidance"
# Industry searches by SIC code prefix, longest prefix first; the fallback is the SIC title.
_SECTORS = (
    ("737", '"cloud computing" OR "AI spending" OR "enterprise software"'),
    ("3674", '"semiconductor demand" OR "AI chips"'),
    ("357", '"PC shipments" OR "smartphone demand"'),
    ("366", '"smartphone demand" OR "telecom equipment"'),
    ("48", '"wireless subscribers" OR "telecom industry"'),
    ("596", '"e-commerce sales" OR "cloud computing"'),
    ("59", '"retail sales" OR "consumer spending"'),
    ("53", '"retail sales" OR "consumer spending"'),
    ("78", '"streaming subscribers" OR "streaming industry"'),
    ("283", '"drug pricing" OR "FDA approval"'),
    ("38", '"medical devices" OR "medtech industry"'),
    ("60", '"interest rates" banks'),
    ("63", '"insurance industry" OR "insurance premiums"'),
    ("13", '"oil prices" OR "oil demand"'),
    ("29", '"oil prices" OR "refining margins"'),
    ("371", '"electric vehicle sales" OR "auto sales"'),
    ("49", '"electricity demand" OR "data center power"'),
    ("45", '"air travel demand" OR airlines'),
)
_CORP = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|com|company|ltd|limited|plc|llc|lp|"
    r"holdings?|group|sa|nv|ag|pbc)\.?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    published: str  # ISO date
    url: str


class NewsProvider(Protocol):
    def search(self, query: str, limit: int) -> list[Headline]: ...


class NewsUnavailable(Exception):
    pass


def _clean(text: str, limit: int = MAX_TITLE) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def parse_rss(xml_text: str, limit: int) -> list[Headline]:
    """Items of an RSS feed. Google News titles end with " - Publisher"; that part is dropped."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NewsUnavailable("The news feed could not be read.") from exc
    out = []
    for item in root.iter("item"):
        source = _clean(item.findtext("source") or "", 80)
        title = _clean(item.findtext("title") or "")
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].rstrip()
        url = (item.findtext("link") or "").strip()
        if not title or not url.startswith("https://"):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            published = ""
        out.append(Headline(title=title, source=source, published=published, url=url))
        if len(out) >= limit:
            break
    return out


class GoogleNewsRSS:
    BASE = "https://news.google.com/rss/search"

    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=settings.news_timeout_seconds)

    def search(self, query: str, limit: int) -> list[Headline]:
        url = f"{self.BASE}?q={quote_plus(query + ' when:30d')}&hl=en-US&gl=US&ceid=US:en"
        try:
            r = self.http.get(url)
        except httpx.HTTPError as exc:
            raise NewsUnavailable("The news feed could not be reached.") from exc
        if r.status_code != 200:
            raise NewsUnavailable(f"The news feed returned HTTP {r.status_code}.")
        return parse_rss(r.text, limit)


def company_query(legal_name: str) -> str:
    """ "MICROSOFT CORP" -> '"Microsoft" (earnings OR ...)': the short name finds the news, the
    business words keep product blogs and encyclopedia pages out."""
    from app.services.intel import display_name

    name = re.sub(r"\s*/[A-Z]{1,5}/?\s*$", "", display_name(legal_name)).strip()
    while (short := _CORP.sub("", name)) != name:
        name = short
    return f'"{name}" ({BUSINESS_WORDS})'


def sector_query(sic_code: str | None, sic_description: str | None) -> str | None:
    code = (sic_code or "").strip()
    for prefix, query in _SECTORS:
        if code.startswith(prefix):
            return query
    words = re.sub(r"[^A-Za-z ]+", " ", sic_description or "").split()
    return f'"{" ".join(words[:3]).lower()}" industry' if words else None


def headlines(
    settings: Settings,
    provider: NewsProvider | None,
    query: str,
    *,
    can_fetch: bool,
    limit: int = 6,
) -> tuple[list[Headline], str | None]:
    """(headlines, fetched_at). Uses the disk cache while it is fresh; otherwise fetches when
    allowed. The public demo key never fetches and sees only fresh cached headlines."""
    path = Path(settings.news_cache_dir) / (hashlib.sha256(query.encode()).hexdigest() + ".json")
    cached = None
    try:
        cached = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        pass
    now = datetime.now(UTC)
    fresh = cached and now - datetime.fromisoformat(cached["fetched_at"]) < timedelta(
        hours=settings.news_cache_hours
    )
    if fresh:
        return [Headline(**h) for h in cached["items"]][:limit], cached["fetched_at"]
    if not (can_fetch and settings.news_enabled and provider is not None):
        return [], None
    try:
        items = provider.search(query, limit)
    except NewsUnavailable as exc:
        log_event(logger, logging.WARNING, "news fetch failed", query=query, error=str(exc))
        return [], None
    entry = {"fetched_at": now.isoformat(), "query": query, "items": [asdict(h) for h in items]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry), "utf-8")
    except OSError as exc:  # the cache is best effort
        log_event(logger, logging.WARNING, "news cache write failed", error=str(exc))
    return items, entry["fetched_at"]
