"""Company search by ticker, CIK, or name. Ranked, bounded, never claims a fuzzy match is exact."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyAlias, Filing
from app.services.sec_client import is_cik_like, normalize_cik

MAX_QUERY_LENGTH = 100


def normalize_ticker(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class SearchHit:
    company: Company
    match_type: str  # cik | ticker | name_exact | name_prefix | name_contains | former_name
    # | name_fuzzy
    score: int
    former_name: str | None = None  # the former name that matched, for former_name hits


_SCORES = {
    "cik": 100,
    "ticker": 90,
    "name_exact": 80,
    "name_prefix": 60,
    "name_contains": 40,
    "former_name": 50,  # below a prefix of the current name, above a word inside one
    "name_fuzzy": 20,
}
# Words that end a name rather than identify it ("Apple Inc." is "apple").
CORP_WORDS = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
    "llc", "lp", "sa", "nv", "ag", "the", "new", "com", "pbc",
}  # fmt: skip
FUZZY_MIN_LENGTH = 5
FUZZY_CANDIDATES = 200
TIE_MARGIN = 0.25
SQLITE_SCAN_LIMIT = 5000


def search_companies(db: Session, query: str, limit: int = 10) -> tuple[list[SearchHit], bool]:
    """Return ranked hits and whether more results were available."""
    q = query.strip()
    if not q or len(q) > MAX_QUERY_LENGTH:
        return [], False
    hits: dict[str, SearchHit] = {}

    if is_cik_like(q):
        cik = normalize_cik(q)
        c = db.scalar(select(Company).where(Company.cik == cik))
        if c:
            hits[c.cik] = SearchHit(c, "cik", _SCORES["cik"])

    ticker = normalize_ticker(q)
    if ticker and len(ticker) <= 12:
        for c in db.scalars(
            select(Company).where(func.upper(Company.ticker) == ticker).limit(limit + 1)
        ):
            hits.setdefault(c.cik, SearchHit(c, "ticker", _SCORES["ticker"]))

    name = normalize_name(q)
    if name and len(name) >= 2:
        pattern_prefix = _escape_like(name) + "%"
        pattern_contains = "%" + _escape_like(name) + "%"
        fetch = limit + 1
        rows = db.scalars(
            select(Company)
            .where(
                or_(
                    func.lower(Company.legal_name).like(pattern_prefix, escape="\\"),
                    func.lower(Company.legal_name).like(pattern_contains, escape="\\"),
                )
            )
            .order_by(Company.legal_name)
            .limit(fetch * 3)
        ).all()
        for c in rows:
            lname = normalize_name(c.legal_name)
            # "apple" is Apple Inc. exactly: the corporate words do not count.
            if lname == name or (core_name(lname) and core_name(lname) == core_name(name)):
                mt = "name_exact"
            elif lname.startswith(name):
                mt = "name_prefix"
            else:
                mt = "name_contains"
            existing = hits.get(c.cik)
            if existing is None or existing.score < _SCORES[mt]:
                hits[c.cik] = SearchHit(c, mt, _SCORES[mt])

        for c, alias in _former_name_matches(db, name, fetch):
            if c.cik not in hits or hits[c.cik].score < _SCORES["former_name"]:
                hits[c.cik] = SearchHit(c, "former_name", _SCORES["former_name"], alias)

    if not hits and len(name) >= FUZZY_MIN_LENGTH:
        for _, c in fuzzy_companies(db, name, limit=limit + 1):
            hits.setdefault(c.cik, SearchHit(c, "name_fuzzy", _SCORES["name_fuzzy"]))
        ordered = list(hits.values())  # already ranked by distance
        return ordered[:limit], len(ordered) > limit

    ordered = sorted(
        hits.values(),
        key=lambda h: (-h.score, not h.company.ticker, h.company.legal_name.lower(), h.company.cik),
    )
    has_more = len(ordered) > limit
    return ordered[:limit], has_more


def _former_name_matches(db: Session, name: str, limit: int) -> list[tuple[Company, str]]:
    """Companies that were once called this: "facebook" finds Meta Platforms."""
    alias = func.lower(CompanyAlias.alias)
    rows = db.execute(
        select(Company, CompanyAlias.alias)
        .join(CompanyAlias, CompanyAlias.cik == Company.cik)
        .where(
            or_(
                alias == name,
                alias.like(_escape_like(name) + "%", escape="\\"),
                alias.like("% " + _escape_like(name) + "%", escape="\\"),
            )
        )
        .order_by((alias == name).desc(), CompanyAlias.valid_to.desc().nulls_last())
        .limit(limit * 3)
    ).all()
    seen, out = set(), []
    for c, a in rows:
        if c.cik not in seen:
            seen.add(c.cik)
            out.append((c, a))
    return out[:limit]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def core_name(name: str) -> str:
    """The words that identify a name: "APPLE INC" is "apple", "Amazon.com, Inc." "amazon"."""
    words = re.findall(r"[a-z0-9&]+", name.lower())
    return " ".join(w for w in words if w not in CORP_WORDS)


def typo_distance(typed: str, name: str) -> float:
    """Edit distance from what was typed to a name, where a dropped letter or two swapped letters
    cost less than a wrong letter: "amazn" is nearer "amazon" (one letter left out) than "amaze"."""
    a, b = typed, name
    d = [[0.0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = float(i)
    for j in range(len(b) + 1):
        d[0][j] = j * 0.8
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0.0 if a[i - 1] == b[j - 1] else 1.0
            d[i][j] = min(d[i - 1][j] + 1.0, d[i][j - 1] + 0.8, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 0.8)
    return d[len(a)][len(b)]


def allowed_typos(phrase: str) -> float:
    return 0.0 if len(phrase) < FUZZY_MIN_LENGTH else 1.0 if len(phrase) <= 6 else 2.0


def fuzzy_companies(
    db: Session, phrase: str, *, limit: int = 5, whole_name: bool = False
) -> list[tuple[float, Company]]:
    """Companies whose name starts with words a typo away from the phrase, nearest first.

    PostgreSQL finds candidates through the trigram index on lower(legal_name); other databases
    (the test suite's SQLite) scan small tables. With whole_name the phrase must cover the whole
    identifying name, so a common word never matches a longer name that merely starts with it."""
    phrase = normalize_name(phrase)
    limit_typos = allowed_typos(phrase)
    if not limit_typos and not whole_name:
        return []
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.3"))
        candidates = db.scalars(
            select(Company)
            .where(func.lower(Company.legal_name).op("%>")(phrase))
            .order_by(func.word_similarity(phrase, func.lower(Company.legal_name)).desc())
            .limit(FUZZY_CANDIDATES)
        ).all()
    elif (db.scalar(select(func.count(Company.id))) or 0) <= SQLITE_SCAN_LIMIT:
        candidates = db.scalars(select(Company)).all()
    else:
        return []
    n = len(phrase.split())
    found = []
    for c in candidates:
        words = core_name(c.legal_name).split()
        # Typos rarely change the first letter; "as today" is not "USA Today".
        if not words or (whole_name and len(words) != n) or words[0][0] != phrase[0]:
            continue
        dist = typo_distance(phrase, " ".join(words[:n]))
        if dist <= limit_typos:
            found.append((dist, c))
    if not found:
        return []
    # Near ties go to the company that files most: "nvidea" means NVIDIA, not Navidea.
    best = min(d for d, _ in found)
    close = [c.cik for d, c in found if d <= best + TIE_MARGIN]
    activity = _recent_filings(db, close)
    found.sort(
        key=lambda x: (
            x[0] > best + TIE_MARGIN,
            not x[1].ticker,
            -activity.get(x[1].cik, 0),
            x[0],
            len(x[1].legal_name),
        )
    )
    return found[:limit]


def _recent_filings(db: Session, ciks: list[str]) -> dict[str, int]:
    if not ciks:
        return {}
    since = date.today() - timedelta(days=365)
    rows = db.execute(
        select(Filing.cik, func.count(Filing.id))
        .where(Filing.cik.in_(ciks), Filing.filing_date >= since)
        .group_by(Filing.cik)
    ).all()
    return {cik: int(n) for cik, n in rows}
