"""D-01b: the company a stopped registrant's own filings name as its successor (display only).

A registrant that stopped filing (mart_company.periodic_active false) often says why in its last
8-K (Item 2.01 or 5.01: "the Company became a wholly owned subsidiary of Parent"), or its
successor says so in an 8-K12B or 8-K12G3 ("HF Sinclair is the successor issuer to
HollyFrontier", Rule 12g-3). This module reads those sentences, as filed, and keeps one link per
stopped registrant with the sentence quoted and its document on EDGAR Archives.

It never joins figures: an acquirer's history is not the acquired company's (that is K-05's
reviewed registrant_successions, app/services/successions.py, which takes precedence). Kinds:
"succeeded" (a successor issuer, a new holding company, or unclear), "acquired" (became a wholly
owned subsidiary of another company) and "merged" (merged with and into another company).

A name is linked only when it is exactly the name of one company held here (case, punctuation and
the legal-form abbreviations Corporation/Corp, Company/Co, Incorporated/Inc, Limited/Ltd aside),
or when the filing is the successor's own (its filer CIK). Otherwise nothing is stored: a
doubtful link is worse than none.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyAlias, Filing, MartCompany, NamedSuccessor, utcnow

PREDECESSOR_ITEMS = ("2.01", "5.01")
SUCCESSOR_FORMS = ("8-K12B", "8-K12G3", "8-K12B/A", "8-K12G3/A")
WINDOW = timedelta(days=400)  # the predecessor's 8-K is read around its last periodic report
KINDS = ("succeeded", "acquired", "merged")
LABELS = {"succeeded": "Succeeded by", "acquired": "Acquired by", "merged": "Merged into"}

_Q = "\"“”'‘’"
_DEF = re.compile(r"\((?:the |collectively, |together, )?[" + _Q + r"](?P<term>[^" + _Q +
                  r"()]{1,40})[" + _Q + r"]\)")  # fmt: skip
_PAREN = re.compile(r"\s*\((?:f/k/a|formerly|fka|now known)[^()]*\)\s*$", re.I)
# a legal-form comma inside a description ("owned by funds managed by affiliates of Apollo Global
# Management, Inc.") does not end it
_SFX = r"(?:,\s*(?:Inc|LLC|L\.L\.C|L\.P|LP|Ltd|N\.V|S\.A|plc|PLC|Corp|Co|AG|SE)\b\.?)"
# never right after another defined term: in 'Topos Acquisition, Inc. ("Merger Sub"), a Delaware
# corporation and wholly owned subsidiary of Tyler Technologies, Inc. ("Parent")' the description
# is Merger Sub's and Parent is Tyler
_DESCR = re.compile(r"(?<![”\"’]\)),\s*(?:an?|the)\s+(?:[^,()]|" + _SFX + r"){0,80}?"
                    r"(?:corporation|company|partnership|trust|société|societe|entity|limited|organized|incorporated)"
                    r"(?:[^,()]|" + _SFX + r")*$", re.I)  # fmt: skip
_WORD = r"(?:[A-Z0-9][\w&'’.\-]*)"
_TAIL = re.compile(r"((?:" + _WORD + r"|of|and|&|de|du|la|the)(?:\s+(?:" + _WORD +
                   r"|of|and|&|de|du|la|the))*(?:,\s*(?:Inc\.?|LLC|L\.L\.C\.|L\.P\.|LP|Ltd\.?|"
                   r"N\.V\.|S\.A\.|plc|PLC|Corp\.?|Co\.|AG|SE))?)\s*$")  # fmt: skip
_SENT = re.compile(r"(?:(?<=[.;][”\"’])|(?<=[.;]))\s+(?=[A-Z(“\"])")
_ABBR = re.compile(r"(?:\b(?:Inc|Corp|Co|Ltd|No|Nos|Mr|Ms|Dr|St|Jr|Sr|Ave|U\.S|L\.P|N\.V|S\.A|"
                   r"L\.L\.C|f/k/a|a/k/a|i\.e|e\.g|vs|Sec|Rule)|\b[A-Z])\.[”\"’]?$")  # fmt: skip

_BECAME = re.compile(r"(?:became|becoming|become|becomes|surviv\w*[^.;]{0,120}?\bas|"
                     r"continu\w*[^.;]{0,140}?\bas)\s+(?:an?\s+|the\s+)?(?:direct\s+|indirect\s+)?"
                     r"wholly[\s\-]+owned\s+(?:direct\s+|indirect\s+)?subsidiar(?:y|ies)\s+of\s+"
                     r"(?P<t>[^.;]{1,160})", re.I)  # fmt: skip
_SUCCESSOR = re.compile(r"(?P<a>[^.;]{1,220}?)\s+(?:is|was|became|has become|will be|shall be|"
                        r"as)\s+(?:the\s+)?[" + _Q + r"]?successor\s+issuer[" + _Q +
                        r"]?\s+(?:to|of)\s+(?P<b>[^.;]{1,160})", re.I)  # fmt: skip
_MERGED = re.compile(r"(?P<s>[^.;]{1,200}?)\s+(?:merged|was merged)\s+with\s+and\s+into\s+"
                     r"(?P<t>[^.;]{1,160})", re.I)  # fmt: skip
_REORG = re.compile(r"holding company (?:reorganization|merger|structure)|new (?:parent )?holding "
                    r"company|parent holding company|Section 251\(g\)|redomicil|"
                    r"successor issuer", re.I)  # fmt: skip
_SUB = re.compile(r"\b(?:merger\s+sub|mergersub|merger\s+subsidiary|sub\s+inc|acquisition\s+"
                  r"(?:corp|co|sub|inc|llc))\b", re.I)  # fmt: skip
_SELF = ("the company", "the registrant", "registrant", "company", "we", "the issuer")

_LEGAL = {"CORPORATION": "CORP", "INCORPORATED": "INC", "COMPANY": "CO", "LIMITED": "LTD"}


def norm(name: str | None) -> str:
    """A name for exact matching: case, punctuation, a leading "The", an EDGAR state tag
    ("/DE/") and the legal-form abbreviations aside. Nothing else is dropped."""
    s = re.sub(r"\s/[A-Z]{2,}/?\s*$", "", (name or "").upper().strip())
    s = s.replace("&", " AND ")
    s = re.sub(r"[.,'’\"“”()]", " ", s)
    words = [_LEGAL.get(w, w) for w in s.split()]
    if words[:1] == ["THE"]:
        words = words[1:]
    return " ".join(words)


def sentences(paras: list[str]) -> list[str]:
    """Each paragraph's sentences; never split after "Inc.", "Corp.", "U.S." and the like."""
    out = []
    for p in paras:
        start = 0
        for m in _SENT.finditer(p):
            if _ABBR.search(p[start : m.start()]):
                continue
            out.append(p[start : m.start()].strip())
            start = m.end()
        out.append(p[start:].strip())
    return [s for s in out if s]


def definitions(text: str) -> dict[str, str]:
    """{defined term: the name it stands for}: 'Express Scripts Holding Company (f/k/a ...) (the
    "Parent")' gives Parent -> Express Scripts Holding Company. The first definition wins."""
    out: dict[str, str] = {}
    for m in _DEF.finditer(text):
        term = m.group("term").strip()
        if term.lower() in out or len(term) < 2:
            continue
        before = text[max(0, m.start() - 260) : m.start()]
        before = re.sub(r"\s+", " ", before).rstrip()
        # ", a Delaware corporation" and "(f/k/a ...)", in either order, each at most once (a
        # second description pass would eat the name: "..., a Delaware corporation and wholly
        # owned subsidiary of Consolidated Communications Holdings, Inc.")
        before, described = _DESCR.subn("", before, count=1)
        before = _PAREN.sub("", before, count=1).rstrip()
        if not described:
            before = _DESCR.sub("", before, count=1).rstrip()
        name = tail_name(before)
        if name:
            out[term.lower()] = name
    return out


def tail_name(chunk: str) -> str | None:
    """The run of capitalised words a chunk ends with ("... by and among the Company, Express
    Scripts, Inc." gives "Express Scripts, Inc.")."""
    m = _TAIL.search(chunk.strip())
    if not m:
        return None
    words = m.group(1).split()
    while words and not re.match(r"[A-Z0-9]", words[0]):
        words = words[1:]  # never start on "of", "and", "the"
    return " ".join(words) or None


def head_names(chunk: str, terms: dict[str, str]) -> list[str]:
    """Names a chunk may start with, longest first: a defined term (resolved) or a run of
    capitalised words, each prefix tried ("Parent, a Delaware corporation" -> the term)."""
    c = re.sub(r"^(?:the|its|a|an)\s+", "", chunk.strip(), flags=re.I)
    stop = (r"\s*(?:,(?!\s*(?:Inc|LLC|L\.L\.C|L\.P|LP|Ltd|N\.V|S\.A|plc|PLC|Corp|Co\.|AG|SE)\b)"
            r"|[(;])|\s+(?:pursuant|effective|following|upon|in accordance|under|which|that|"
            r"on|as of|with|and the|in connection)\b")
    c = re.split(stop, c, maxsplit=1)[0]
    if _SUB.search(c):
        return []  # "Prologis Merger Sub": a merger subsidiary, never the term it starts with
    out = []
    for term, name in terms.items():
        rest = c[len(term) :].strip() if c.lower().startswith(term) else None
        if rest == "" or (rest and c.lower().startswith(term + " ") and rest[0].islower()):
            out.append(name)
    words = c.split()
    for n in range(len(words), 0, -1):
        out.append(" ".join(words[:n]))
    return out


def _tail_names(chunk: str, terms: dict[str, str]) -> list[str]:
    """Names a chunk may end with (a subject): a defined term or the trailing capitalised run,
    each suffix tried, longest first."""
    c = chunk.strip().rstrip(",")
    out = []
    for term, name in terms.items():
        if c.lower().endswith(term):
            out.append(name)
    name = tail_name(re.split(r"[,(]\s*(?=[a-z])", c)[-1])
    if name:
        words = name.split()
        out += [" ".join(words[i:]) for i in range(len(words))]
    return out


class Names:
    """Exact-name lookup over the companies held here (current names; a former name counts only
    when no current name matches and the name was in force at the evidence date)."""

    def __init__(self, db: Session):
        self.current: dict[str, set[str]] = {}
        for cik, name in db.execute(select(Company.cik, Company.legal_name)):
            self.current.setdefault(norm(name), set()).add(cik)
        self.former: dict[str, list[tuple[str, date | None]]] = {}
        rows = db.execute(select(CompanyAlias.cik, CompanyAlias.alias, CompanyAlias.valid_to)
                          .where(CompanyAlias.kind == "former"))  # fmt: skip
        for cik, alias, to in rows:
            self.former.setdefault(norm(alias), []).append((cik, to))

    def find(self, name: str, on: date, exclude: str) -> str | None:
        key = norm(name)
        if len(key) < 4:
            return None
        got = self.current.get(key, set()) - {exclude}
        if not got:
            got = {c for c, to in self.former.get(key, [])
                   if c != exclude and (to is None or to >= on)}  # fmt: skip
        return next(iter(got)) if len(got) == 1 else None


def _refers_to_self(chunk: str, self_names: set[str], terms: dict[str, str],
                    at: str = "end") -> bool:  # fmt: skip
    """Whether the chunk ends (the subject before "became"/"merged") or starts (the object after
    "successor issuer to") with the filer: "the Company", "the Registrant", a term defined as
    the filer, or the filer's own name."""
    c = re.sub(r"\s+", " ", chunk).strip()
    if at == "end":
        for _ in range(3):  # a defined term or "(as defined ...)" right after the subject
            c = re.sub(r"\s*\([^()]*\)\s*,?$", "", c).rstrip(" ,")
    else:
        c = re.sub(r"^(?:to|of)\s+", "", c, flags=re.I)
    low = c.lower()
    tokens = list(_SELF[:3]) + [t for t, n in terms.items() if norm(n) in self_names]

    def hit(t: str) -> bool:
        t = re.escape(t)
        pat = r"(?:^|\W)" + t + r"$" if at == "end" else r"^(?:the\s+)?" + t + r"(?:\W|$)"
        return re.search(pat, low) is not None

    if any(hit(t) for t in tokens):
        return True
    key = norm(c)
    return any(n and (key.endswith(n) if at == "end" else key.startswith(n)) for n in self_names)


def _quote(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= 600 else s[:597].rstrip() + "..."


def read_predecessor(paras: list[str], filer_cik: str, self_names: set[str], names: Names,
                     on: date) -> dict | None:  # fmt: skip
    """The successor a stopped registrant's own 8-K names: a successor-issuer sentence first,
    then "became a wholly owned subsidiary of", then "merged with and into"."""
    text = "\n".join(paras)
    terms = definitions(text)
    reorg = bool(_REORG.search(text))
    found = []
    for s in sentences(paras):
        for m in _SUCCESSOR.finditer(s):
            if _refers_to_self(m.group("b")[:120], self_names, terms, at="start"):
                for n in _tail_names(m.group("a"), terms):
                    if cik := names.find(n, on, filer_cik):
                        found.append((0, "succeeded", cik, n, s))
                        break
        for m in _BECAME.finditer(s):
            head = s[: m.start()]
            if not _refers_to_self(head[-160:], self_names, terms):
                continue
            for n in head_names(m.group("t"), terms):
                if _SUB.search(n):
                    break
                if cik := names.find(n, on, filer_cik):
                    found.append((1, "succeeded" if reorg else "acquired", cik, n, s))
                    break
        for m in _MERGED.finditer(s):
            if not _refers_to_self(m.group("s")[-120:], self_names, terms):
                continue
            for n in head_names(m.group("t"), terms):
                if _SUB.search(n):
                    break
                if cik := names.find(n, on, filer_cik):
                    found.append((2, "succeeded" if reorg else "merged", cik, n, s))
                    break
    if not found:
        return None
    rank, kind, cik, name, s = min(found, key=lambda f: f[0])
    return {"successor_cik": cik, "kind": kind, "name_as_filed": name, "quote": _quote(s),
            "match_method": "name"}  # fmt: skip


def read_successor(paras: list[str], filer_cik: str, self_names: set[str], names: Names,
                   on: date) -> dict | None:  # fmt: skip
    """The predecessor a successor's own 8-K12B/8-K12G3 names ("X is the successor issuer to Y"):
    the successor is the filer (its own CIK), the predecessor must match a company by name."""
    text = "\n".join(paras)
    terms = definitions(text)
    for s in sentences(paras):
        for m in _SUCCESSOR.finditer(s):
            if not _refers_to_self(m.group("a")[-160:], self_names, terms):
                continue
            for n in head_names(m.group("b"), terms):
                if cik := names.find(n, on, filer_cik):
                    return {"predecessor_cik": cik, "successor_cik": filer_cik,
                            "kind": "succeeded", "name_as_filed": n, "quote": _quote(s),
                            "match_method": "filer_cik"}  # fmt: skip
    return None


def candidates(db: Session) -> tuple[list[Filing], list[Filing], dict[str, MartCompany]]:
    """The predecessors' 8-Ks (Item 2.01 or 5.01, within 400 days of their last periodic report)
    and every successor 8-K12B/8-K12G3 held; and the stopped registrants."""
    stopped = {m.cik: m for m in db.scalars(select(MartCompany).where(
        MartCompany.periodic_active.is_(False),
        MartCompany.last_periodic_date.is_not(None)))}  # fmt: skip
    pred = []
    for f in db.scalars(select(Filing).where(Filing.form_type.in_(("8-K", "8-K/A")),
                                             Filing.cik.in_(list(stopped)))):  # fmt: skip
        items = (f.items or "").split(",")
        last = stopped[f.cik].last_periodic_date
        if any(i in PREDECESSOR_ITEMS for i in items) and f.filing_date and \
                last - WINDOW <= f.filing_date <= last + WINDOW:  # fmt: skip
            pred.append(f)
    succ = list(db.scalars(select(Filing).where(Filing.form_type.in_(SUCCESSOR_FORMS))))
    return pred, succ, stopped


def choose(rows: list[dict]) -> dict[str, dict]:
    """One link per predecessor: a successor-issuer statement first, then the latest filing.
    Two different successors from equally strong evidence leave the predecessor out."""
    best: dict[str, dict] = {}
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["predecessor_cik"], []).append(r)
    for cik, rs in by.items():
        top = min(_strength(r) for r in rs)
        strongest = [r for r in rs if _strength(r) == top]
        if len({r["successor_cik"] for r in strongest}) > 1:
            continue
        best[cik] = max(strongest, key=lambda r: r["evidence_date"])
    return best


def _strength(r: dict) -> int:
    return 0 if r["match_method"] == "filer_cik" or "successor issuer" in r["quote"].lower() else 1


def store(db: Session, chosen: dict[str, dict]) -> dict:
    """Upsert one row per predecessor (a re-run corrects a row in place)."""
    have = {r.predecessor_cik: r for r in db.scalars(select(NamedSuccessor))}
    added = changed = 0
    for cik, r in chosen.items():
        row = have.get(cik)
        vals = {k: r[k] for k in ("successor_cik", "kind", "name_as_filed", "quote", "match_method",
                                  "evidence_accession", "evidence_form", "evidence_date",
                                  "evidence_url")}  # fmt: skip
        if row is None:
            db.add(NamedSuccessor(predecessor_cik=cik, updated_at=utcnow(), **vals))
            added += 1
        elif any(getattr(row, k) != v for k, v in vals.items()):
            for k, v in vals.items():
                setattr(row, k, v)
            row.updated_at = utcnow()
            changed += 1
    return {"added": added, "changed": changed}


def succeeded_by(db: Session, cik: str) -> dict | None:
    """The overview's succeeded_by: shown for a registrant that stopped filing; K-05's reviewed
    successor (the overview's `successor`) takes precedence."""
    from app.services.intel import display_name

    r = db.get(NamedSuccessor, cik)
    if r is None:
        return None
    c = db.scalar(select(Company).where(Company.cik == r.successor_cik))
    return {
        "cik": r.successor_cik,
        "name": c.legal_name if c else r.name_as_filed,
        "name_as_filed": r.name_as_filed,
        "display_name": display_name(c.legal_name, c.ticker, c.registrant_name) if c else None,
        "kind": r.kind,
        "label": LABELS[r.kind],
        "quote": r.quote,
        "filed_date": r.evidence_date.isoformat(),
        "form": r.evidence_form,
        "document_url": r.evidence_url,
        "basis": "Named in the filing quoted; display only, figures are never joined.",
    }
