"""Company search by ticker, CIK, or name. Ranked, bounded, never claims a fuzzy match is exact."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Company
from app.services.sec_client import is_cik_like, normalize_cik

MAX_QUERY_LENGTH = 100


def normalize_ticker(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


@dataclass
class SearchHit:
    company: Company
    match_type: str  # cik | ticker | name_exact | name_prefix | name_contains
    score: int


_SCORES = {"cik": 100, "ticker": 90, "name_exact": 80, "name_prefix": 60, "name_contains": 40}


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
            if lname == name:
                mt = "name_exact"
            elif lname.startswith(name):
                mt = "name_prefix"
            else:
                mt = "name_contains"
            existing = hits.get(c.cik)
            if existing is None or existing.score < _SCORES[mt]:
                hits[c.cik] = SearchHit(c, mt, _SCORES[mt])

    ordered = sorted(hits.values(), key=lambda h: (-h.score, h.company.legal_name, h.company.cik))
    has_more = len(ordered) > limit
    return ordered[:limit], has_more


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
