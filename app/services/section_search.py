"""Full-text search over stored filing sections (issue #2, step 2).

PostgreSQL matches with websearch_to_tsquery against a stored tsvector column with a GIN index
(migration b9d4e2f7a6c1) and ranks with ts_rank_cd on that stored vector. Other databases (the test
suite's SQLite) count query terms in Python, which is enough for small tables. Snippets are cut in
Python around the first query term, because ts_headline re-parses whole sections.
Every hit carries its filing's form, date, accession number and index page; nothing else is linked.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import Filing, FilingSection
from app.services import prospectus, releases
from app.services.form8k import ITEM_TITLES

MAX_QUERY_LENGTH = 200
MAX_LIMIT = 50
SNIPPET_WORDS = 35
# The query term that names a section ("risk factors", "use of proceeds") lifts that section.
TITLE_BOOST = 1.5
_EN = literal_column("'english'::regconfig")
_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "by", "with", "is", "are", "was",
    "what", "how", "who", "which", "does", "do", "did", "its", "their", "about", "from", "at",
}  # fmt: skip


@dataclass
class SectionHit:
    cik: str
    accession_number: str
    item: str
    title: str
    form_type: str | None
    filing_date: date | None
    source_url: str
    rank: float
    snippet: str


def section_title(item: str) -> str:
    if item in prospectus.TITLES:
        return prospectus.TITLES[item]
    if item == releases.ITEM:
        return "Earnings release (exhibit 99.1)"
    if item in ITEM_TITLES:
        return f"8-K item {item}: {ITEM_TITLES[item]}"
    return item


def search_sections(
    db: Session,
    query: str,
    *,
    cik: str | None = None,
    forms: list[str] | None = None,
    as_of: date | None = None,
    limit: int = 10,
) -> list[SectionHit]:
    """Sections that match the words of the query, best first. With as_of, only sections of
    filings dated on or before it; with cik or forms, only those."""
    query = " ".join(query.split())[:MAX_QUERY_LENGTH]
    limit = max(1, min(limit, MAX_LIMIT))
    if not _terms(query):
        return []
    stmt = (
        select(FilingSection, Filing.form_type, Filing.filing_date)
        .join(
            Filing,
            (Filing.cik == FilingSection.cik)
            & (Filing.accession_number == FilingSection.accession_number),
        )
        .where(FilingSection.status == "ok", FilingSection.text.is_not(None))
    )
    if cik:
        stmt = stmt.where(FilingSection.cik == cik)
    if forms:
        stmt = stmt.where(Filing.form_type.in_(forms))
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    if db.get_bind().dialect.name == "postgresql":
        return _postgres(db, stmt, query, limit)
    return _scan(db, stmt, query, limit)


# The generated column exists only on PostgreSQL, so it is not part of the ORM model.
_VECTOR = literal_column("filing_sections.search_vector")


def _postgres(db: Session, stmt, query: str, limit: int) -> list[SectionHit]:
    tsq = func.websearch_to_tsquery(_EN, query)
    rank = func.ts_rank_cd(_VECTOR, tsq, 32)  # 32: rank / (rank + 1), between 0 and 1
    rows = db.execute(
        stmt.add_columns(rank.label("rank"))
        .where(_VECTOR.op("@@")(tsq))
        .order_by(rank.desc(), Filing.filing_date.desc().nulls_last())
        .limit(limit * 3)
    ).all()
    hits = _rerank(query, [(s, form, filed, float(r)) for s, form, filed, r in rows])[:limit]
    terms = _terms(query)
    return [_hit(s, form, filed, r, _snippet(s.text or "", terms)) for s, form, filed, r in hits]


def _scan(db: Session, stmt, query: str, limit: int) -> list[SectionHit]:
    terms = _terms(query)
    scored = []
    for s, form, filed in db.execute(stmt).all():
        words = _WORD.findall((s.text or "").lower())
        if not words:
            continue
        counts = {t: sum(1 for w in words if w.startswith(t)) for t in terms}
        if not all(counts.values()):
            continue
        score = sum(math.log1p(n) for n in counts.values()) / math.log(len(words) + 10)
        scored.append((s, form, filed, score / (score + 1)))
    hits = _rerank(query, scored)[:limit]
    return [_hit(s, form, filed, r, _snippet(s.text or "", terms)) for s, form, filed, r in hits]


def _rerank(query: str, rows: list[tuple]) -> list[tuple]:
    q = query.lower()
    out = []
    for s, form, filed, rank in rows:
        if section_title(s.item).lower() in q:
            rank *= TITLE_BOOST
        out.append((s, form, filed, rank))
    out.sort(key=lambda x: (-x[3], -(x[2] or date.min).toordinal()))
    return out


def _hit(s: FilingSection, form, filed, rank: float, snippet: str) -> SectionHit:
    return SectionHit(
        cik=s.cik,
        accession_number=s.accession_number,
        item=s.item,
        title=section_title(s.item),
        form_type=form,
        filing_date=filed,
        source_url=s.source_url,
        rank=round(rank, 4),
        snippet=" ".join(snippet.split()),
    )


def _terms(query: str) -> list[str]:
    words = [w for w in _WORD.findall(query.lower()) if w not in _STOP and len(w) >= 2]
    # A crude stem so "risks" finds "risk" in the scan, as the English configuration does.
    return list(dict.fromkeys(w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words))


def _stem(term: str) -> str:
    """A loose stem for spotting a term in raw text: "resigned" finds "resignation"."""
    return term if len(term) <= 5 else term[: max(5, len(term) - 2)]


def _snippet(text: str, terms: list[str]) -> str:
    """About SNIPPET_WORDS words around the stretch that holds the most different query terms."""
    span = SNIPPET_WORDS * 7  # characters, about seven per word
    stems = [_stem(t) for t in terms]
    pattern = re.compile(r"\b(" + "|".join(re.escape(st) for st in stems) + ")", re.IGNORECASE)
    marks = [(m.start(), m.group(1).lower()) for m in pattern.finditer(text)]
    if not marks:
        return " ".join(text[:span].split()[:SNIPPET_WORDS])
    best, at = -1, 0
    for j, (pos, _) in enumerate(marks):
        inside = {st for p, st in marks[j:] if p < pos + span - 60}
        if len(inside) > best:
            best, at = len(inside), pos
        if best == len(stems):
            break
    begin = text.rfind(" ", 0, max(0, at - 60)) + 1
    words = text[begin : begin + span + 40].split()
    return " ".join(words[:SNIPPET_WORDS])
