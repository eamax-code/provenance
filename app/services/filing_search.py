"""Q-01: full-text search inside stored filing sections (docs/contracts/filing-search.md).

Matching uses the stored tsvector and its GIN index (websearch_to_tsquery: words by English stem,
quoted phrases, `or`, `-` exclusions). A quoted phrase is then checked against the text itself,
case and punctuation aside and without stemming, so every hit holds the phrase as written.

Form, filing date and section of every stored section come from a small in-process map (about
20,000 rows, reloaded every INDEX_TTL_SECONDS), so filters and the date sort need no join on the
filings table: joining 15,000 matches of a common word to their filings took most of a second.
Relevance ranks the newest RELEVANCE_POOL matches (ranking reads each section's stored vector).
Other databases (the test suite's SQLite) match in Python.
"""

from __future__ import annotations

import itertools
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, literal_column, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.db.models import Filing, FilingSection
from app.services.section_search import TITLE_BOOST, section_title

MAX_QUERY_LENGTH = 200
MAX_LIMIT = 50
MAX_OFFSET = 500
MAX_PHRASES = 8
SNIPPET_WORDS = 35
SNIPPET_MARKS = 50  # occurrences of each term considered when placing the snippet
RELEVANCE_POOL = 2000
PHRASE_CHUNK = 500  # candidates checked by the phrase operator at a time
VERIFY_BATCH = 100
MAX_SCANNED = 5000  # candidates checked for a phrase before the page is cut short
MAX_TEXT_READS = 800  # section texts read to check phrases before the page is cut short
INDEX_TTL_SECONDS = 600

FAMILIES = {
    "annual_report": lambda item: item.startswith("10k:"),
    "prospectus": lambda item: item.startswith("pr:"),
    "earnings_release": lambda item: item == "ex:99.1",
    "8k_officers": lambda item: item == "5.02",
}
_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_TOKEN = re.compile(r'(-?)"([^"]*)"?|(\S+)')
_STOP = {
    "the", "a", "an", "and", "of", "to", "in", "on", "for", "by", "with", "is", "are", "was",
    "its", "their", "from", "at", "as", "be", "or", "not", "this", "that", "it",
}  # fmt: skip
_EN = literal_column("'english'::regconfig")
_VECTOR = literal_column("filing_sections.search_vector")


class InvalidQuery(ValueError):
    pass


@dataclass
class Term:
    words: list[str]
    phrase: bool
    negated: bool = False

    @property
    def text(self) -> str:
        return " ".join(self.words)


@dataclass
class Query:
    q: str
    groups: list[list[Term]]  # every group must hold; one term of a group is enough
    excluded: list[Term] = field(default_factory=list)
    stems: dict[str, str] = field(default_factory=dict)  # PostgreSQL's English stem of each word
    # the forms of each word in the texts shown whose PostgreSQL stem is the word's own ("going"
    # finds "go", "goes", "going", never "goods" or "governance"); None until a page is read
    forms: dict[str, set[str]] | None = None

    @property
    def terms(self) -> list[Term]:
        return [t for g in self.groups for t in g]

    @property
    def phrases(self) -> list[str]:
        return [t.text for t in self.terms if t.phrase]

    @property
    def words(self) -> list[str]:
        return [t.text for t in self.terms if not t.phrase]


def parse(q: str) -> Query:
    """The query as websearch_to_tsquery reads it: `or` joins the terms on either side."""
    q = " ".join((q or "").split())[:MAX_QUERY_LENGTH]
    groups: list[list[Term]] = []
    excluded: list[Term] = []
    join_next = False
    for neg, quoted, bare in _TOKEN.findall(q):
        if bare and bare.lower() == "or":
            join_next = bool(groups)
            continue
        if bare:
            neg, raw = ("-", bare[1:]) if bare.startswith("-") else ("", bare)
            terms = [Term([w], False) for w in _WORD.findall(raw.lower()) if w not in _STOP]
        else:
            words = _WORD.findall(quoted.lower())
            # a quoted single word is matched by its stem, as unquoted: exact single words would
            # need a second, unstemmed index ("activations" stems to "activ", thousands of
            # sections, each read to find the rare exact word: over a second)
            terms = [Term(words, len(words) > 1)] if words else []
        for t in terms:
            if neg:
                t.negated = True
                excluded.append(t)
            elif join_next:
                groups[-1].append(t)
            else:
                groups.append([t])
            join_next = False
    query = Query(q, groups, excluded)
    if not any(w not in _STOP for t in query.terms for w in t.words):
        raise InvalidQuery("The query has no word to search for (common words are ignored).")
    if len(query.phrases) > MAX_PHRASES:
        raise InvalidQuery(f"At most {MAX_PHRASES} quoted phrases.")
    return query


def _phrase_re(words: list[str]) -> re.Pattern:
    return re.compile(r"\b" + r"[\W_]+".join(re.escape(w) for w in words) + r"\b", re.IGNORECASE)


def _stem(word: str) -> str:
    """A loose stem for spotting a word in raw text ("tariffs" finds "tariff")."""
    if len(word) > 4 and word.endswith("s"):
        word = word[:-1]
    return word if len(word) <= 5 else word[: max(5, len(word) - 2)]


_NEVER = re.compile(r"(?!x)x")


def _word_re(word: str, stems: dict[str, str] | None = None,
             forms: dict[str, set[str]] | None = None) -> re.Pattern:  # fmt: skip
    """A word in raw text by its stem, never by prefix: with the forms PostgreSQL stems to the
    word's stem (search reads them for the page shown), exactly those; else by a stem prefix of
    four letters or more, or the word as written when the stem is shorter ("go" for "going")."""
    if forms is not None and word in forms:
        got = sorted(forms[word], key=len, reverse=True)
        if not got:
            return _NEVER
        return re.compile(r"\b(?:" + "|".join(re.escape(f) for f in got) + r")\b", re.IGNORECASE)
    pre = _prefix(word, stems)
    if stems and stems.get(word) and len(pre) < 4:
        return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
    return re.compile(r"\b" + re.escape(pre) + r"\w*", re.IGNORECASE)


def _prefix(word: str, stems: dict[str, str] | None = None) -> str:
    """The part of the word its stem shares, to find candidate forms in raw text."""
    stem = (stems or {}).get(word)
    # PostgreSQL's stem is not always a prefix of the word or its forms ("fiduciary" is
    # "fiduciari", "diversify" is "diversifi"): without the y-turned-i, the part the stem and the
    # word share finds the word and its forms in the text
    if stem and len(stem) > 4 and stem.endswith("i"):
        stem = stem[:-1]
    stem = os.path.commonprefix([stem, word]) if stem else _stem(word)
    if len(stem) < 3:
        stem = (stems or {}).get(word) or _stem(word)
    return stem


def _holds(term: Term, text: str, stems: dict[str, str] | None = None,
           forms: dict[str, set[str]] | None = None) -> bool:  # fmt: skip
    pat = _phrase_re(term.words) if term.phrase else _word_re(term.text, stems, forms)
    return bool(pat.search(text))


def verify(query: Query, text: str, trust_words: bool) -> bool:
    """Every phrase as written. With trust_words (PostgreSQL matched the stems), a group of words
    only is taken as matched; otherwise each group needs one of its terms in the text."""
    for g in query.groups:
        if trust_words and not any(t.phrase for t in g):
            continue
        if not any(_holds(t, text, query.stems, query.forms) for t in g):
            return False
    if not trust_words and any(_holds(t, text, query.stems, query.forms) for t in query.excluded):
        return False
    return True


def tsquery(query: Query, phrases: bool = False):
    """The query for the GIN index. A quoted phrase is matched here as all of its words, which
    the index answers alone; word order and adjacency are checked in the text (verify): the
    phrase operator would make PostgreSQL re-read each candidate's stored vector (about 300 ms
    for a common phrase). An excluded phrase keeps the phrase operator."""

    out = None

    def term(t: Term):  # with phrases=True, positive phrases keep the phrase operator too
        if t.phrase and (t.negated or phrases):
            return func.phraseto_tsquery(_EN, t.text)
        return func.plainto_tsquery(_EN, t.text)

    for g in query.groups:
        alt = None
        for t in g:
            alt = term(t) if alt is None else func.tsquery_or(alt, term(t))
        out = alt if out is None else func.tsquery_and(out, alt)
    for t in query.excluded:
        out = func.tsquery_and(out, func.tsquery_not(term(t)))
    return out


# -- the section map ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    id: uuid.UUID
    cik: str
    accession_number: str
    item: str
    form: str
    filed: date | None
    source_url: str
    family: str | None = None


_index: tuple[float, list[Row], dict[uuid.UUID, Row]] | None = None
_coverage: list[dict] | None = None
_index_lock = threading.Lock()


def section_map(db: Session) -> tuple[list[Row], dict[uuid.UUID, Row]]:
    global _index
    with _index_lock:
        if _index and time.monotonic() - _index[0] < INDEX_TTL_SECONDS:
            return _index[1], _index[2]
    rows = [
        Row(i, c, a, it, (f or "").upper(), d, u, family(it))
        for i, c, a, it, f, d, u in db.execute(
            select(FilingSection.id, FilingSection.cik, FilingSection.accession_number,
                   FilingSection.item, Filing.form_type, Filing.filing_date,
                   FilingSection.source_url)
            .join(Filing, (Filing.cik == FilingSection.cik)
                  & (Filing.accession_number == FilingSection.accession_number))
            .where(FilingSection.status == "ok", FilingSection.text.is_not(None))
        )
    ]  # fmt: skip
    rows.sort(key=lambda r: (r.filed or date.min, r.accession_number, r.item), reverse=True)
    by_id = {r.id: r for r in rows}
    global _coverage
    with _index_lock:
        _index = (time.monotonic(), rows, by_id)
        _coverage = None
    return rows, by_id


def reset_section_map() -> None:
    global _index, _coverage
    with _index_lock:
        _index = None
        _coverage = None


def family(item: str) -> str | None:
    return next((name for name, test in FAMILIES.items() if test(item)), None)


def coverage(db: Session) -> list[dict]:
    """Per section family: items, forms, counts and dates; computed once per section map."""
    global _coverage
    rows, _ = section_map(db)
    with _index_lock:
        if _coverage is not None:
            return [dict(c) for c in _coverage]
    out: dict[str, dict] = {}
    for r in rows:
        fam = r.family or r.item
        c = out.setdefault(fam, {
            "section": fam, "items": set(), "forms": set(), "sections": 0, "ciks": set(),
            "first_filed": None, "last_filed": None})  # fmt: skip
        c["items"].add(r.item)
        c["forms"].add(r.form)
        c["sections"] += 1
        c["ciks"].add(r.cik)
        if r.filed:
            c["first_filed"] = min(filter(None, (c["first_filed"], r.filed)))
            c["last_filed"] = max(filter(None, (c["last_filed"], r.filed)))
    result = [
        {"section": c["section"], "items": sorted(c["items"]), "forms": sorted(c["forms"]),
         "sections": c["sections"], "companies": len(c["ciks"]),
         "first_filed": c["first_filed"].isoformat() if c["first_filed"] else None,
         "last_filed": c["last_filed"].isoformat() if c["last_filed"] else None}
        for c in sorted(out.values(), key=lambda c: -c["sections"])
    ]  # fmt: skip
    with _index_lock:
        _coverage = result
    return [dict(c) for c in result]


def known_items(db: Session) -> set[str]:
    return {r.item for r in section_map(db)[0]}


# -- search ------------------------------------------------------------------------------------


@dataclass
class Filters:
    cik: str | None = None
    forms: list[str] | None = None
    section: str | None = None  # a family name or one item code
    items: set[str] | None = None  # chat: several item codes ("risk factors")
    filed_from: date | None = None
    filed_to: date | None = None
    allowed: set[str] | None = None  # the demo key's showcase companies

    def keep(self, r: Row) -> bool:
        if self.cik and r.cik != self.cik:
            return False
        if self.allowed is not None and r.cik not in self.allowed:
            return False
        if self.forms and not any(r.form == f or r.form == f + "/A" for f in self.forms):
            return False
        if self.section and r.item != self.section and r.family != self.section:
            return False
        if self.items is not None and r.item not in self.items:
            return False
        if self.filed_from and (r.filed is None or r.filed < self.filed_from):
            return False
        return not (self.filed_to and (r.filed is None or r.filed > self.filed_to))


@dataclass
class Hit:
    row: Row
    snippet: str
    highlights: list[list[int]]
    relevance: float | None
    # Q-09: for Items 1A and 7, where the hit starts in the section's text as filed (the text
    # /v1/filings/{accession}/sections/{item} returns), so a reader can open at it
    section_offset: int | None = None


@dataclass
class Result:
    hits: list[Hit]
    has_more: bool
    truncated: bool = False  # stopped after MAX_SCANNED sections


def search(db: Session, query: Query, filters: Filters, sort: str = "date", limit: int = 20,
           offset: int = 0) -> Result:  # fmt: skip
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))
    rows, by_id = section_map(db)
    pg = db.get_bind().dialect.name == "postgresql"
    if pg:
        tsq = tsquery(query)
        # The planner prefers a sequential scan for a common word, which reads every section's
        # stored vector (about 650 ms); the GIN index alone answers it in about 10 ms.
        db.execute(sql_text("SET LOCAL enable_seqscan = off"))
        matched = set(db.scalars(select(FilingSection.id).where(_VECTOR.op("@@")(tsq))))
        candidates = [r for r in rows if r.id in matched and filters.keep(r)]
        db.execute(sql_text("SET LOCAL enable_seqscan = on"))
        query.stems = _pg_stems(db, query)
    else:
        candidates = [r for r in rows if filters.keep(r)]
    scores: dict[uuid.UUID, float] = {}
    if sort == "relevance":
        candidates = candidates[:RELEVANCE_POOL]
        scores = _rank(db, query, candidates, pg)
        candidates = [r for r in candidates if r.id in scores]
        candidates.sort(key=lambda r: (-scores[r.id], -(r.filed or date.min).toordinal()))
    need = offset + limit + 1
    check = not pg or bool(query.phrases)
    found: list[tuple[Row, str | None]] = []
    scanned, reads, truncated = 0, 0, False
    # Common words, rare phrase ("share second"): reading thousands of texts to find the phrase
    # took seconds. PostgreSQL's phrase operator checks a chunk of candidates first (about 0.06
    # ms a section against 0.35 ms to read one), and only those texts are read and checked.
    phrase_q = tsquery(query, phrases=True) if pg and query.phrases else None
    chunk_size = PHRASE_CHUNK if phrase_q is not None else VERIFY_BATCH
    if not check:
        found = [(r, None) for r in candidates[:need]]
    else:
        for i in range(0, len(candidates), chunk_size):
            if len(found) >= need:
                break
            if scanned >= MAX_SCANNED or truncated:
                truncated = True
                break
            chunk = candidates[i : i + chunk_size]
            scanned += len(chunk)
            if phrase_q is not None:
                ids = [r.id for r in chunk]
                # the test in the select list: evaluated on these rows only (in WHERE, the
                # planner answered it from the GIN index over the whole table, every chunk)
                hit = _VECTOR.op("@@")(phrase_q)
                rows_ok = db.execute(select(FilingSection.id, hit).where(FilingSection.id.in_(ids)))
                near = {i for i, ok in rows_ok if ok}
                chunk = [r for r in chunk if r.id in near]
            for j in range(0, len(chunk), VERIFY_BATCH):
                if len(found) >= need:
                    break
                if reads >= MAX_TEXT_READS:  # a phrase PostgreSQL cannot narrow ("will be")
                    truncated = True
                    break
                batch = chunk[j : j + VERIFY_BATCH]
                reads += len(batch)
                texts = _texts(db, [r.id for r in batch])
                found += [(r, texts[r.id]) for r in batch if r.id in texts
                          and verify(query, texts[r.id], trust_words=pg)]  # fmt: skip
    page = found[offset : offset + limit]
    missing = [r.id for r, t in page if t is None]
    texts = _texts(db, missing) if missing else {}
    filed = _filed_texts(db, [r.id for r, _ in page if r.item.startswith("10k:")])
    if pg and query.words:
        shown = [t if t is not None else texts.get(r.id, "") for r, t in page]
        query.forms = _pg_forms(db, query, shown + [v for v in filed.values() if v])
    hits = []
    for r, t in page:
        text = t if t is not None else texts.get(r.id, "")
        snippet, marks = snippet_for(query, text)
        at = hit_at(query, filed[r.id]) if filed.get(r.id) else None
        hits.append(Hit(r, snippet, marks, round(scores[r.id], 4) if r.id in scores else None,
                        at))  # fmt: skip
    return Result(hits, has_more=len(found) > offset + limit, truncated=truncated)


def _filed_texts(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(FilingSection.id, FilingSection.filed_text)
                           .where(FilingSection.id.in_(ids))).all())  # fmt: skip


def _pg_stems(db: Session, query: Query) -> dict[str, str]:
    """PostgreSQL's English stem of each query word ("activations" is "activ"), so highlights
    and checks find the words the index matched."""
    words = sorted({w for t in [*query.terms, *query.excluded] for w in t.words})
    if not words:
        return {}
    cols = [func.array_to_string(func.tsvector_to_array(func.to_tsvector(_EN, w)), " ")
            for w in words]  # fmt: skip
    got = db.execute(select(*cols)).one()
    return {w: g.split()[0] for w, g in zip(words, got, strict=True) if g}


def _pg_forms(db: Session, query: Query, texts: list[str]) -> dict[str, set[str]]:
    """Each query word's forms in these texts that PostgreSQL stems to the word's own stem: the
    words sharing the stem's prefix are stemmed in one query and kept only on an exact match."""
    seen: dict[str, set[str]] = {}
    for w in query.words:
        pat = re.compile(r"\b" + re.escape(_prefix(w, query.stems)) + r"\w*", re.IGNORECASE)
        seen[w] = {m.group(0).lower() for t in texts for m in pat.finditer(t)} | {w.lower()}
    tokens = sorted(set().union(*seen.values())) if seen else []
    if not tokens:
        return {}
    got = dict(db.execute(sql_text(
        "select w, array_to_string(tsvector_to_array(to_tsvector('english', w)), ' ') "
        "from unnest(cast(:ws as text[])) as w"), {"ws": tokens}).all())  # fmt: skip
    return {w: {f for f in seen[w] if got.get(f) and got[f] == query.stems.get(w)}
            for w in seen}  # fmt: skip


def _texts(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(FilingSection.id, FilingSection.text)
                           .where(FilingSection.id.in_(ids))).all())  # fmt: skip


def _rank(db: Session, query: Query, rows: list[Row], pg: bool) -> dict[uuid.UUID, float]:
    if not rows:
        return {}
    titled = {r.id for r in rows if section_title(r.item).lower() in query.q.lower()}
    if pg:
        tsq = tsquery(query)
        rank = func.ts_rank_cd(_VECTOR, tsq, 32)  # 32: rank / (rank + 1), between 0 and 1
        ids = [r.id for r in rows]
        scored = dict(db.execute(select(FilingSection.id, rank)
                                 .where(FilingSection.id.in_(ids))).all())  # fmt: skip
    else:
        scored = {}
        texts = _texts(db, [r.id for r in rows])
        for r in rows:
            t = texts.get(r.id) or ""
            if not verify(query, t, trust_words=False):
                continue
            n = sum(len(_word_re(w, query.stems, query.forms).findall(t)) for w in query.words)
            n += sum(len(_phrase_re(p.split()).findall(t)) for p in query.phrases)
            scored[r.id] = n / (n + len(t.split()) / 50 + 1)
    return {k: min(1.0, float(v) * (TITLE_BOOST if k in titled else 1)) for k, v in scored.items()}


def _patterns(query: Query) -> list[re.Pattern]:
    return [_phrase_re(t.words) if t.phrase else _word_re(t.text, query.stems, query.forms)
            for t in query.terms]  # fmt: skip


def _best_at(pats: list[re.Pattern], text: str) -> int | None:
    """Where the stretch holding the most different terms starts (a term's first character), or
    None when no term is in the text."""
    marks = sorted((m.start(), k) for k, p in enumerate(pats)
                   for m in itertools.islice(p.finditer(text), SNIPPET_MARKS))  # fmt: skip
    span = SNIPPET_WORDS * 7
    at, best = None, -1
    for j, (pos, _) in enumerate(marks):
        inside = {k for p, k in marks[j:] if p < pos + span - 60}
        if len(inside) > best:
            best, at = len(inside), pos
        if best == len(pats):
            break
    return at


def hit_at(query: Query, text: str) -> int | None:
    """Q-09: the hit's character offset in a section's text as filed (see Hit.section_offset)."""
    return _best_at(_patterns(query), text)


def snippet_for(query: Query, text: str) -> tuple[str, list[list[int]]]:
    """About SNIPPET_WORDS words around the stretch that holds the most different terms, as plain
    text, with [start, end) offsets of each phrase or word shown."""
    pats = _patterns(query)
    at = _best_at(pats, text) or 0
    begin = text.rfind(" ", 0, max(0, at - 60)) + 1 if at else 0
    words = text[begin:].split()
    body = " ".join(words[:SNIPPET_WORDS])
    snippet = ("… " if begin > 0 else "") + body + (" …" if len(words) > SNIPPET_WORDS else "")
    spans = sorted({(m.start(), m.end()) for p in pats for m in p.finditer(snippet)})
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return snippet, merged
