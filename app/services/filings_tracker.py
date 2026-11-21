"""Filings tracker (ADR 0012): every filing EDGAR disseminates, read every hour.

Three public EDGAR indexes:

- EDGAR full-text search (`efts.sec.gov/LATEST/search-index`) answers in under a second and
  holds each document-based filing within minutes. It is asked for today's and yesterday's
  going-public forms (S-1, F-1, 424B4, 8-A, Form 10, DRS, RW), then periodic and current reports.
  It is not complete for Forms 3, 4 and 5;
- the latest-filings feed (`browse-edgar?action=getcurrent`) lists about the last 2,000 filings of
  every form. It is read page by page until a page holds only filings already seen; it is often
  slow, so a timeout ends the read for that run;
- the daily index (`master.YYYYMMDD.idx`) is published each evening with every filing of that
  day. It is read once per day as the complete record, so whatever the other two missed (the job
  was down, a busy hour ran past the pages) is filled the next day.

Each filing is kept once per company it names (a Form 4 names its issuer). Then, under a per-run
budget, oldest first:

- a company already covered is refreshed: its filings, its XBRL facts after a periodic report,
  and its Forms 3, 4 and 5 after an insider filing. New filings reach the event feed and watch
  notifications within the hour;
- a company not covered is added when its form shows a public company or one going public
  (`DISCOVERY_FORMS`: a registration statement, a final prospectus, an exchange listing, a
  periodic report). The filings the tracker saw go to the event feed;
- anything else (funds, private placements, people's own filings) is recorded and left alone.

SEC fair access: one request per feed page, one per daily index, and one or two per company
refreshed; the SEC client paces every request under ten a second.
"""

from __future__ import annotations

import html
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Company, EdgarFeedEntry, Filing, JobState, utcnow
from app.services import insider_activity, insiders, ipo_terms, marts, notifications, universe
from app.services.events import publish_pending
from app.services.ingestion import IngestionError, ingest_company
from app.services.sec_client import SecClient, SecClientError, normalize_cik

logger = logging.getLogger("app.jobs.filings_tracker")
EASTERN = ZoneInfo("America/New_York")

LATEST_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&company=&dateb="
    "&owner=include&start={start}&count=100&output=atom"
)
DAILY_URL = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/master.{ymd}.idx"
SEARCH_URL = (
    "https://efts.sec.gov/LATEST/search-index?q=&forms={forms}&dateRange=custom"
    "&startdt={start}&enddt={end}&from={offset}"
)
# Full-text search matches amendments by their root form (S-1 finds S-1/A).
SEARCH_GOING_PUBLIC = ("S-1", "F-1", "424B4", "8-A12B", "8-A12G", "10-12B", "10-12G", "DRS", "RW")
SEARCH_REPORTS = ("10-K", "10-Q", "20-F", "40-F", "8-K", "6-K")
SEARCH_PAGES = 30  # 100 hits a page
DAILY_STATE = "filings_tracker.daily_index"
DAILY_FIRST_DAYS = 5  # the first run reads this many days of daily indexes back
MAX_ATTEMPTS = 3

# Going public and listing: registration, effectiveness, exchange listing, final prospectus.
IPO_FORMS = frozenset({
    "S-1", "S-1/A", "F-1", "F-1/A", "S-1MEF", "F-1MEF", "DRS", "DRS/A", "424B4", "EFFECT",
    "8-A12B", "8-A12B/A", "8-A12G", "8-A12G/A", "CERT", "RW", "10-12B", "10-12B/A", "10-12G",
    "10-12G/A",
})  # fmt: skip
PERIODIC = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"})
INSIDER = frozenset({"3", "3/A", "4", "4/A", "5", "5/A"})
# A company not covered yet is added for these. EFFECT and CERT are left out: funds and
# exchange-traded products file them too, and a company going public files an S-1 or 8-A first.
DISCOVERY_FORMS = frozenset({
    "S-1", "S-1/A", "F-1", "F-1/A", "424B4", "8-A12B", "8-A12G", "10-12B", "10-12G", "10-K",
    "10-Q", "20-F", "40-F",
})  # fmt: skip
LISTING_ONLY = frozenset({"8-A12B", "8-A12G"})
# Funds and exchange-traded products register listings on 8-A too; these mark them.
FUND_FORMS = re.compile(r"^(485|497|N-|40-17|24F|S-6|NT N|POS AM \(?N)")
FUND_NAME = re.compile(r"\b(ETF|ETFs|Fund|Funds|Trust|Portfolio|Series)\b", re.I)
TERMS_FORMS = frozenset({"424B4", "S-1/A", "F-1/A", "S-1", "F-1"})
ROLES = {"Filer": "filer", "Subject": "subject", "Issuer": "issuer"}  # not Reporting, Filed by

_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_HEAD = re.compile(r"^(?P<form>.+?) - (?P<name>.*) \((?P<cik>\d{10})\) \((?P<role>[^)]*)\)$")
_TERM = re.compile(r'label="form type" term="([^"]+)"')
_ACCESSION = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
_FILED = re.compile(r"Filed:</b>\s*(\d{4}-\d{2}-\d{2})")
_UPDATED = re.compile(r"<updated>(.*?)</updated>")
_INDEX_PATH = re.compile(r"edgar/data/\d+/(\d{10}-\d{2}-\d{6})\.txt$")


@dataclass(frozen=True)
class Entry:
    accession_number: str
    cik: str
    company_name: str
    form_type: str
    role: str
    filing_date: date | None
    accepted_at: datetime | None


def discovers(forms: set[str], name: str) -> bool:
    """Whether filings in `forms` make a company not yet covered worth adding."""
    if not forms & DISCOVERY_FORMS or any(FUND_FORMS.match(f) for f in forms):
        return False
    if forms & DISCOVERY_FORMS <= LISTING_ONLY and FUND_NAME.search(name):
        return False  # an exchange-traded fund or trust listing a class
    return True


def priority(form: str) -> int:
    """Order of handling within a run: going public first, insider filings last."""
    if form in IPO_FORMS:
        return 0
    if form in PERIODIC:
        return 1
    if form in INSIDER:
        return 3
    return 2


# ---- reading -------------------------------------------------------------------------------


def parse_latest(text: str) -> list[Entry]:
    """Company entries of the latest-filings Atom feed (not the people who report on them)."""
    out: list[Entry] = []
    for body in _ENTRY.findall(text):
        title, acc = _TITLE.search(body), _ACCESSION.search(body)
        if not title or not acc:
            continue
        m = _HEAD.match(html.unescape(title.group(1)).strip())
        if not m or m.group("role") not in ROLES:
            continue
        term = _TERM.search(body)
        filed = _FILED.search(html.unescape(body))
        upd = _UPDATED.search(body)
        try:
            accepted = datetime.fromisoformat(upd.group(1)) if upd else None
        except ValueError:
            accepted = None
        out.append(
            Entry(
                accession_number=acc.group(1),
                cik=m.group("cik"),
                company_name=m.group("name").strip(),
                form_type=html.unescape(term.group(1)) if term else m.group("form"),
                role=ROLES[m.group("role")],
                filing_date=date.fromisoformat(filed.group(1)) if filed else None,
                accepted_at=accepted,
            )
        )
    return out


def parse_daily_index(text: str) -> list[Entry]:
    """Rows of a daily master index: CIK|Company Name|Form Type|Date Filed|File Name."""
    out: list[Entry] = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 5 or not parts[0].strip().isdigit():
            continue
        cik, name, form, filed, path = (p.strip() for p in parts)
        acc = _INDEX_PATH.search(path)
        if not acc or len(filed) != 8:
            continue
        out.append(
            Entry(
                accession_number=acc.group(1),
                cik=normalize_cik(cik),
                company_name=name,
                form_type=form,
                role="listed",
                filing_date=date(int(filed[:4]), int(filed[4:6]), int(filed[6:])),
                accepted_at=None,
            )
        )
    return out


def parse_search(payload: dict) -> list[Entry]:
    """Hits of EDGAR full-text search: one entry per company a filing names."""
    out: list[Entry] = []
    for hit in (payload.get("hits") or {}).get("hits") or []:
        src = hit.get("_source") or {}
        acc, filed = src.get("adsh"), src.get("file_date")
        form = src.get("form") or src.get("file_type")
        if not acc or not form:
            continue
        names = src.get("display_names") or []
        for i, cik in enumerate(src.get("ciks") or []):
            name = re.sub(r"\s+\(.*$", "", names[i]).strip() if i < len(names) else cik
            out.append(
                Entry(
                    accession_number=acc, cik=normalize_cik(cik), company_name=name or cik,
                    form_type=form, role="filer" if i == 0 else "listed",
                    filing_date=date.fromisoformat(filed) if filed else None, accepted_at=None,
                )
            )  # fmt: skip
    return out


def read_search(db: Session, client: SecClient, now: datetime | None = None) -> dict:
    """Today's and yesterday's document filings from full-text search: going public first."""
    today = (now or utcnow()).astimezone(EASTERN).date()
    start = (today - timedelta(days=1)).isoformat()
    out: dict = {"entries": 0, "new": 0}
    for forms in (SEARCH_GOING_PUBLIC, SEARCH_REPORTS):
        for page in range(SEARCH_PAGES):
            url = SEARCH_URL.format(forms=",".join(forms), start=start, end=today.isoformat(),
                                    offset=page * 100)  # fmt: skip
            try:
                payload = client.get_json(url).data
            except SecClientError as exc:
                out["error"] = str(exc)
                break
            entries = parse_search(payload)
            out["entries"] += len(entries)
            out["new"] += record(db, entries, "search")
            hits = (payload.get("hits") or {}).get("hits") or []
            if len(hits) < 100:
                break
    return out


def record(db: Session, entries: list[Entry], source: str, now: datetime | None = None) -> int:
    """Keep each (filing, company) once. Returns how many were new."""
    now = now or utcnow()
    fresh = list({(e.accession_number, e.cik): e for e in entries}.values())
    added = 0
    for i in range(0, len(fresh), 500):
        chunk = fresh[i : i + 500]
        have = set(
            db.execute(
                select(EdgarFeedEntry.accession_number, EdgarFeedEntry.cik).where(
                    EdgarFeedEntry.accession_number.in_({e.accession_number for e in chunk})
                )
            ).all()
        )
        for e in chunk:
            if (e.accession_number, e.cik) in have:
                continue
            db.add(
                EdgarFeedEntry(
                    accession_number=e.accession_number, cik=e.cik, company_name=e.company_name,
                    form_type=e.form_type, role=e.role, filing_date=e.filing_date,
                    accepted_at=e.accepted_at, source=source, seen_at=now, status="new",
                    attempts=0,
                )
            )  # fmt: skip
            added += 1
    db.commit()
    return added


def read_latest(db: Session, client: SecClient, pages: int) -> dict:
    """Page through the latest-filings feed until a page brings nothing new. The feed is often
    slow, so one retry, and a failed page ends the read (the daily index fills the gap)."""
    client = client.with_retries(1)
    seen = added = 0
    for page in range(pages):
        try:
            text = client.get_text(LATEST_URL.format(start=page * 100)).data
        except SecClientError as exc:
            log_event(logger, logging.WARNING, "latest filings feed unavailable", error=str(exc))
            return {"entries": seen, "new": added, "error": str(exc)}
        entries = parse_latest(text)
        if not entries and "<entry>" not in text:
            break
        seen += len(entries)
        got = record(db, entries, "latest")
        added += got
        if entries and got == 0:
            break
    return {"entries": seen, "new": added}


def _business_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def read_daily_indexes(db: Session, client: SecClient, now: datetime | None = None) -> dict:
    """Read each daily index not read yet, through yesterday (US Eastern)."""
    today = (now or utcnow()).astimezone(EASTERN).date()
    state = db.get(JobState, DAILY_STATE)
    first = today - timedelta(days=DAILY_FIRST_DAYS + 1)
    last = date.fromisoformat(state.value) if state else first
    out = {"days": [], "new": 0}
    for day in _business_days(last + timedelta(days=1), today - timedelta(days=1)):
        url = DAILY_URL.format(y=day.year, q=(day.month - 1) // 3 + 1, ymd=day.strftime("%Y%m%d"))
        try:
            text = client.get_text(url).data
        except SecClientError as exc:
            if exc.status_code in (403, 404) and (today - day).days > 4:
                pass  # a holiday: no index is published
            else:
                out["error"] = f"{day}: {exc}"
                break  # try again next run
        else:
            out["new"] += record(db, parse_daily_index(text), "daily-index")
            out["days"].append(day.isoformat())
        last = day
        if state is None:
            state = JobState(name=DAILY_STATE, value=last.isoformat())
            db.add(state)
        state.value, state.updated_at = last.isoformat(), utcnow()
        db.commit()
    return out


# ---- acting on what was read ---------------------------------------------------------------


def _publish_seen(db: Session, cik: str, accessions: set[str], settings: Settings) -> None:
    """A company found by the tracker: the recent filings it saw go to the event feed."""
    oldest = utcnow().date() - timedelta(days=settings.notify_max_filing_age_days)
    db.execute(
        update(Filing)
        .where(
            Filing.cik == cik,
            Filing.accession_number.in_(accessions),
            Filing.stream_status == "skipped",
            Filing.filing_date >= oldest,
        )
        .values(stream_status="pending")
        .execution_options(synchronize_session=False)
    )


def handle(
    db: Session, settings: Settings, client: SecClient, max_companies: int, run=None
) -> dict:
    """Refresh or add the companies named by new filings, at most `max_companies` per run."""
    rows = db.scalars(
        select(EdgarFeedEntry)
        .where(EdgarFeedEntry.status.in_(("new", "failed")), EdgarFeedEntry.attempts < MAX_ATTEMPTS)
        .order_by(EdgarFeedEntry.seen_at, EdgarFeedEntry.id)
    ).all()
    by_cik: dict[str, list[EdgarFeedEntry]] = defaultdict(list)
    for r in rows:
        by_cik[r.cik].append(r)
    covered = set()
    ciks = list(by_cik)
    for i in range(0, len(ciks), 500):
        covered |= set(db.scalars(select(Company.cik).where(Company.cik.in_(ciks[i : i + 500]))))
    order = sorted(ciks, key=lambda c: (min(priority(r.form_type) for r in by_cik[c]), c))
    actionable = [
        c for c in order
        if c in covered or discovers({r.form_type for r in by_cik[c]}, by_cik[c][0].company_name)
    ]  # fmt: skip
    out = {"companies": len(actionable), "refreshed": 0, "discovered": 0, "ignored": 0, "failed": 0,
           "insider_filings": 0, "discovered_names": []}  # fmt: skip
    keep = set(actionable)
    ignored = [r.id for c in order if c not in keep for r in by_cik[c]]
    for i in range(0, len(ignored), 1000):
        db.execute(
            update(EdgarFeedEntry)
            .where(EdgarFeedEntry.id.in_(ignored[i : i + 1000]))
            .values(status="ignored", handled_at=utcnow())
            .execution_options(synchronize_session=False)
        )
    out["ignored"] = len(order) - len(actionable)
    db.commit()
    touched: list[str] = []
    done = 0
    for cik in actionable[:max_companies]:  # the rest wait for the next run
        group = by_cik[cik]
        forms = {r.form_type for r in group}
        now = utcnow()
        done += 1
        new = cik not in covered
        try:
            ingest_company(
                db, client, cik, run=run,
                include_facts=new or bool(forms & PERIODIC),
                history_pages=None if new else 0,
            )  # fmt: skip
            if forms & INSIDER:
                before = insider_activity.accessions(db, cik)
                out["insider_filings"] += insiders.fill_recent(db, client, cik, limit=20)["fetched"]
                fresh = None if new else insider_activity.accessions(db, cik) - before
                found = insider_activity.store(
                    db, cik, fresh, insider_activity.coverage_start(db)
                )  # backfill for a company first seen now; new activity otherwise (F-03)
                notifications.create_insider_deliveries(db, found)
                out["insider_activity"] = out.get("insider_activity", 0) + len(found)
            if forms & TERMS_FORMS:  # deal terms from the prospectus (F-02)
                out["ipo_terms"] = out.get("ipo_terms", 0) + ipo_terms.read_company(db, cik, client)
            if new:
                universe.ensure_member(db, cik, source="tracker", now=now)
                _publish_seen(db, cik, {r.accession_number for r in group}, settings)
                out["discovered_names"].append(f"{group[0].company_name} ({sorted(forms)[0]})")
            status = "discovered" if new else "refreshed"
            out[status] += 1
            touched.append(cik)
            detail = None
        except (SecClientError, IngestionError) as exc:
            db.rollback()
            status, detail = "failed", str(exc)[:500]
            out["failed"] += 1
        if run is not None:
            run = db.merge(run)
        ids = [g.id for g in group]
        for r in db.scalars(select(EdgarFeedEntry).where(EdgarFeedEntry.id.in_(ids))):
            r.status, r.handled_at, r.detail = status, utcnow(), detail
            r.attempts += 1
        db.commit()
    db.commit()
    if touched:
        marts.build_company_marts(db, touched)
        db.commit()
    publish_pending(db)
    out["left"] = len(actionable) - done
    return out


def run_once(
    db: Session, settings: Settings, client: SecClient, daily: bool = True, run=None
) -> dict:
    """Read the feed (and any daily index not read yet), then act on it."""
    summary: dict = {"search": read_search(db, client)}
    summary["latest"] = read_latest(db, client, settings.filings_tracker_feed_pages)
    if daily:
        summary["daily_index"] = read_daily_indexes(db, client)
    summary.update(handle(db, settings, client, settings.filings_tracker_max_companies, run))
    log_event(
        logger, logging.INFO, "filings tracker",
        **{k: v for k, v in summary.items() if k != "discovered_names"},
        discovered_list=", ".join(summary["discovered_names"])[:500],
    )  # fmt: skip
    return summary


def status(db: Session) -> dict:
    by = select(EdgarFeedEntry.status, func.count()).group_by(EdgarFeedEntry.status)
    counts = dict(db.execute(by).all())
    state = db.get(JobState, DAILY_STATE)
    return {
        "by_status": counts,
        "last_seen_at": db.scalar(select(func.max(EdgarFeedEntry.seen_at))),
        "daily_index_through": state.value if state else None,
    }
