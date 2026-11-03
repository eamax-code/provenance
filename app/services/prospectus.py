"""Registration statements (S-1, F-1 and final prospectuses) read as text.

A company that has filed to go public has no annual XBRL figures yet; its numbers, risks and
plans are in the prospectus. The latest registration document is fetched once, cut into its
main sections by the table of contents, and stored. A question then gets the few passages that
match it best, plus the summary financial table, each cited to the filing.
"""

from __future__ import annotations

import html
import logging
import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Filing, FilingSection
from app.services.officer_changes import document_url, html_to_text
from app.services.sec_client import SecClient, SecClientError

logger = logging.getLogger("app.prospectus")

FORMS = ("S-1", "S-1/A", "F-1", "F-1/A", "424B4", "424B1")
PREFIX = "pr:"
NONE_ITEM = "pr:none"  # marks a document that was fetched but had no usable section
MAX_SECTION_CHARS = 250_000
RECENT_YEARS = 3  # a registration this old is still worth quoting for an established filer
# (key, title shown in citations, table-of-contents title pattern)
SECTIONS = (
    ("pr:summ", "Prospectus summary", r"(prospectus )?summary"),
    ("pr:risk", "Risk factors", r"risk factors"),
    ("pr:use", "Use of proceeds", r"use of proceeds"),
    ("pr:div", "Dividend policy", r"dividend policy"),
    ("pr:cap", "Capitalization", r"capitali[sz]ation"),
    ("pr:dil", "Dilution", r"dilution"),
    ("pr:mdna", "Management's discussion and analysis", r"management.s discussion.*"),
    ("pr:biz", "Business", r"(our )?business"),
    ("pr:mgmt", "Management", r"management|(our )?directors and (executive )?officers"),
    ("pr:pay", "Executive compensation", r"executive compensation"),
    ("pr:owner", "Principal stockholders", r"principal( and selling)? (stock|share)holders"),
    ("pr:uw", "Underwriting", r"underwriting.*|plan of distribution"),
)
TITLES = {key: title for key, title, _ in SECTIONS}
_PATTERNS = [(key, re.compile(rf"^(?:{pat})$", re.IGNORECASE)) for key, _, pat in SECTIONS]
_TOC_LINK = re.compile(r'(?is)<a\b[^>]*href="#([^"]+)"[^>]*>(.*?)</a>')
_ROW = re.compile(r"(?is)<tr\b.*?</tr>")
_CELL = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")
_FIN_TABLE = re.compile(r"summary (consolidated )?(financial|historical)", re.IGNORECASE)
_WORD = re.compile(r"[a-z][a-z0-9-]+")
_STOP = set(
    "the a an and or of to in on for is are was were be by with as at it its this that what how "
    "which who whom does do did has have had about from their there they them can could would "
    "should will tell me us our your you any all more much many some show give explain".split()
)
# Words that point to a section, so a short question still finds the right passages.
_HINTS = {
    "pr:risk": {"risk", "risks", "threat", "threats", "danger", "concern", "concerns"},
    "pr:use": {"proceeds", "raise", "raising", "spend", "ipo", "offering"},
    "pr:cap": {"capitalization", "debt", "cash", "valuation"},
    "pr:dil": {"dilution", "dilutive", "dilute"},
    "pr:mdna": {"revenue", "revenues", "loss", "losses", "margin", "growth", "expenses",
                "costs", "profit", "income", "results", "financial", "financials"},
    "pr:biz": {"business", "products", "product", "customers", "competition", "strategy",
               "model", "models", "market"},
    "pr:mgmt": {"ceo", "cfo", "management", "board", "directors", "executives", "founders",
                "founder", "founded", "leadership", "officers", "runs", "run", "leads", "led",
                "president", "chair", "chairman", "chairperson", "team"},
    "pr:pay": {"compensation", "salary", "pay", "bonus", "equity"},
    "pr:owner": {"owns", "owner", "owners", "stockholders", "shareholders", "investors",
                 "stake", "ownership"},
    "pr:uw": {"underwriters", "underwriter", "banks", "underwriting"},
}  # fmt: skip
_IPO_Q = re.compile(
    r"\b(ipo|s-1|f-1|prospectus|go(?:ing)? public|went public|offering|listing|list(?:ed|s)? on|"
    r"use of proceeds|proceeds|underwrit\w*|dilution|lock-?up|risk factors?|risks?)\b",
    re.IGNORECASE,
)


def is_prospectus_question(text: str) -> bool:
    return bool(_IPO_Q.search(text))


# -- reading the document -----------------------------------------------------------------


def _cell(raw: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(raw)).strip()


def _row(m: re.Match) -> str:
    cells = [c for c in (_cell(x) for x in _CELL.findall(m.group(0))) if c]
    line = " | ".join(cells)
    # Filers put "$", ")" and "%" in cells of their own.
    line = re.sub(r"\$ \| ", "$", line)
    line = re.sub(r" \| ([)%])", r"\1", line)
    return f"<p>{html.escape(line)}</p>" if line else ""


_PAGE_NOISE = re.compile(r"(?im)^[ \t]*(?:\d{1,3}|[A-Z]-\d{1,3}|table of contents)[ \t]*\n")


def to_text(doc: str) -> str:
    """Document text with each table row on one line, cells separated by " | ", and without
    page numbers and the "Table of Contents" link printed on every page."""
    return _PAGE_NOISE.sub("", html_to_text(_ROW.sub(_row, doc)) + "\n").strip()


def _section_key(title: str) -> str | None:
    title = re.sub(r"\s+", " ", title).strip(" .:")
    for key, pat in _PATTERNS:
        if pat.match(title):
            return key
    return None


def split_sections(doc: str) -> dict[str, str]:
    """Main sections by the table of contents' links; by heading lines when there are none."""
    marks: dict[str, int] = {}
    keys: dict[str, str] = {}
    for anchor, inner in _TOC_LINK.findall(doc):
        if anchor in marks:
            continue
        found = re.search(rf'\b(?:id|name)="{re.escape(anchor)}"', doc)
        if not found:
            continue
        marks[anchor] = found.start()
        key = _section_key(_cell(inner))
        if key and key not in keys.values():
            keys[anchor] = key
    if len(keys) >= 2:
        bounds = sorted(marks.values())
        out = {}
        for anchor, key in keys.items():
            start = marks[anchor]
            end = next((b for b in bounds if b > start), len(doc))
            # Cut at the tags that hold the anchors, not inside them.
            text = to_text(doc[doc.rfind("<", 0, start) : doc.rfind("<", 0, end)])
            text = text[:MAX_SECTION_CHARS]
            if len(text) > 80:
                out[key] = text
        if len(out) >= 2:
            return out
    return _split_by_headings(to_text(doc))


def _split_by_headings(text: str) -> dict[str, str]:
    """Fallback: a heading is a line that is only a section title. The table of contents names
    each title too, so the longest stretch up to the next heading wins."""
    lines = text.split("\n")
    heads = [(i, _section_key(line)) for i, line in enumerate(lines) if len(line) < 80]
    heads = [(i, k) for i, k in heads if k]
    best: dict[str, str] = {}
    for n, (i, key) in enumerate(heads):
        end = next((j for j, k in heads[n + 1 :] if k != key), len(lines))
        chunk = "\n".join(lines[i:end])[:MAX_SECTION_CHARS]
        if len(chunk) > len(best.get(key, "")):
            best[key] = chunk
    return {k: v for k, v in best.items() if len(v) > 80}


# -- storage ----------------------------------------------------------------------------------


def latest_registration(
    db: Session, cik: str, as_of: date | None = None, *, max_age_years: int | None = None
) -> Filing | None:
    stmt = select(Filing).where(Filing.cik == cik, Filing.form_type.in_(FORMS))
    ref = as_of or date.today()
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    if max_age_years:
        stmt = stmt.where(Filing.filing_date >= ref - timedelta(days=365 * max_age_years))
    return db.scalars(
        stmt.order_by(Filing.filing_date.desc(), Filing.accession_number.desc()).limit(1)
    ).first()


def stored_sections(db: Session, accession_number: str) -> list[FilingSection]:
    return list(
        db.scalars(
            select(FilingSection).where(
                FilingSection.accession_number == accession_number,
                FilingSection.item.like(PREFIX + "%"),
            )
        )
    )


def ensure_read(db: Session, f: Filing, sec: SecClient | None) -> str:
    """Fetch and store the document's sections once. Returns read, stored, not_read or failed.

    With `sec` None nothing is fetched."""
    if stored_sections(db, f.accession_number):
        return "stored"
    if sec is None:
        return "not_read"
    url = document_url(f)
    now = datetime.now(UTC)
    sections: dict[str, str] = {}
    status = "fetch_failed"
    if url:
        try:
            sections = split_sections(sec.get_text(url).data)
            status = "ok" if sections else "no_section"
        except SecClientError as exc:
            log_event(logger, logging.WARNING, "prospectus fetch failed", url=url, error=str(exc))
    for key, text in sections.items():
        db.add(
            FilingSection(
                cik=f.cik,
                accession_number=f.accession_number,
                item=key,
                status="ok",
                text=text,
                source_url=url,
                fetched_at=now,
            )
        )
    if not sections:
        db.add(
            FilingSection(
                cik=f.cik,
                accession_number=f.accession_number,
                item=NONE_ITEM,
                status=status,
                text=None,
                source_url=url or f.source_url,
                fetched_at=now,
            )
        )
    db.commit()
    return "read" if sections else "failed"


# -- passages for a question --------------------------------------------------------------


def _chunks(text: str, size: int = 900) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


_YEAR = re.compile(r"(?:19|20)\d\d")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split(" | ")]


def label_columns(text: str) -> str:
    """Name every figure in a table by its period. A header such as "2023 | 2024 | 2025 | 2025 |
    2026" under "Year Ended December 31, | Nine Months Ended September 30," becomes
    "Year Ended December 31, 2023" ... "Nine Months Ended September 30, 2026", so a reader
    cannot take one period's figure for another's."""
    out: list[str] = []
    labels: list[str] = []
    prev = ""
    for line in text.split("\n"):
        cells = _cells(line)
        years = cells[1:]
        if len(cells) > 2 and all(_YEAR.fullmatch(y) for y in years):
            runs: list[list[str]] = [[years[0]]]
            for y in years[1:]:
                if y <= runs[-1][-1]:
                    runs.append([])
                runs[-1].append(y)
            periods = [p.rstrip(",") for p in _cells(prev) if p and not p.startswith("(")]
            labels = (
                [f"{per}, {y}" for per, run in zip(periods, runs, strict=True) for y in run]
                if len(periods) == len(runs)
                else years
            )
            if cells[0]:
                out.append(f"Amounts {cells[0].strip('()')}.")
        elif labels and len(cells) == len(labels) + 1:
            line = (
                cells[0]
                + ": "
                + "; ".join(f"{lab}: {v}" for lab, v in zip(labels, cells[1:], strict=True))
            )
            out.append(line)
        else:
            if " | " not in line and line.strip() and not line.strip().endswith(":"):
                labels = labels if len(line) < 60 else []
            out.append(line)
        prev = line
    return "\n".join(out)


def key_figures(sections: dict[str, str], limit: int = 4000) -> str | None:
    """The summary financial table from the prospectus summary, its rows labelled by period."""
    summ = sections.get("pr:summ") or ""
    m = _FIN_TABLE.search(summ)
    if not m:
        return None
    rows = summ.find(" | ", m.end())  # the table itself, not the paragraph introducing it
    if rows < 0:
        return None
    start = summ.rfind("\n", 0, summ.rfind("\n", 0, rows)) + 1
    return label_columns(summ[start : start + limit * 2])[:limit]


_OVERVIEW = re.compile(r"(?im)^\s*(overview|our company|company overview|our business)\s*$")


def overview(sections: dict[str, str], limit: int = 1800) -> str | None:
    """What the company does, from the summary's "Overview" rather than its standard preamble."""
    summ = sections.get("pr:summ") or sections.get("pr:biz")
    if not summ:
        return None
    m = _OVERVIEW.search(summ, 0, 6000)
    return summ[m.start() if m else 0 :][:limit].strip()


_SYNONYMS = {
    "ceo": "chief executive officer",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
    "cto": "chief technology officer",
    "ipo": "offering proceeds",
    "money": "proceeds",
    "raise": "proceeds offering",
    "raising": "proceeds offering",
    "owns": "beneficially owned",
    "investors": "stockholders beneficially owned",
}
# Where a section's best overview starts: the risk summary sits in the prospectus summary.
_LEADS = {"pr:risk": ("pr:summ", re.compile(r"(summary )?risk factors( summary)?", re.I))}


# Sections whose table says more than their opening paragraphs: who holds the shares, who
# the officers are, the capitalization.
_TABLE_FIRST = {"pr:owner", "pr:mgmt", "pr:cap"}


def _lead(sections: dict[str, str], key: str, limit: int) -> str | None:
    where, heading = _LEADS.get(key, (key, None))
    text = sections.get(where) or ""
    if heading is not None:
        m = next((m for m in heading.finditer(text) if m.group(1) or m.group(2)), None)
        text = text[text.rfind("\n", 0, m.start()) + 1 :] if m else sections.get(key, "")
    if key in _TABLE_FIRST and " | " in text:
        row = text.index(" | ")
        text = text[text.rfind("\n", 0, text.rfind("\n", 0, row)) + 1 :]
        limit = 2500
    return text[:limit].strip() or None


def passages(
    sections: dict[str, str], question: str, *, ignore: set[str] = frozenset(), budget: int = 6000
) -> list[tuple[str, str]]:
    """What best answers the question: the opening of each section the question points to, then
    the chunks that share most of its words (rare words count more), within a character budget."""
    asked = [w for w in _terms(question) if w not in ignore]
    q = set(_terms(" ".join(_SYNONYMS.get(w, w) for w in asked)))
    hinted = [key for key, hints in _HINTS.items() if (q | set(asked)) & hints and key in sections]
    out: list[tuple[str, str]] = []
    used = 0
    for key in hinted[:2]:
        lead = _lead(sections, key, 1500)
        if lead:
            out.append((key, lead))
            used += len(lead)
    pool = [(key, c) for key, text in sections.items() for c in _chunks(text)]
    if not pool or not q:
        return out
    df = Counter(t for _, c in pool for t in set(_terms(c)) if t in q)
    scored = []
    for key, c in pool:
        tf = Counter(t for t in _terms(c) if t in q)
        score = sum((1 + math.log(n)) * math.log(1 + len(pool) / df[t]) for t, n in tf.items())
        if score and key in hinted:
            score *= 2
        if score:
            scored.append((score, key, c))
    scored.sort(key=lambda x: -x[0])
    for _, key, c in scored:
        if used + len(c) > budget or any(c.strip() in t for _, t in out):
            continue
        out.append((key, c.strip()))
        used += len(c)
    return out


def add_to_brief(b, db: Session, f: Filing, question: str) -> bool:
    """Cite the registration document and add its overview, key figures and best passages."""
    rows = [r for r in stored_sections(db, f.accession_number) if r.status == "ok" and r.text]
    if not rows:
        return False
    sections = {r.item: r.text for r in rows}
    url = rows[0].source_url
    head = f"{f.form_type} filed {f.filing_date}"
    b.coverage["prospectus"] = {
        "form_type": f.form_type,
        "filed_date": f.filing_date.isoformat(),
        "source_url": url,
        "sections": sorted(TITLES[k] for k in sections if k in TITLES),
    }
    cites: dict[str, int] = {}

    def cite(key: str) -> int:
        if key not in cites:
            cites[key] = b.cite(f"{head}, {TITLES.get(key, 'prospectus')}", url)
        return cites[key]

    b.context_lines.append(
        f"[{cite('pr:summ')}] The company filed a registration statement to sell shares to the "
        f"public ({head}). The passages below are quoted from it; amounts in tables are as "
        "labelled there (often in millions)."
    )
    name = set(_terms(b.company.legal_name)) | {(b.company.ticker or "").lower()}
    picked = [("pr:summ", t) for t in (overview(sections), key_figures(sections)) if t]
    picked += [
        p for p in passages(sections, question, ignore=name) if p[1] not in {t for _, t in picked}
    ]
    for key, text in picked:
        quote = re.sub(r"[ \t]*\n[ \t]*", " / ", text)
        b.context_lines.append(f"[{cite(key)}] From {head}, {TITLES[key]}: {quote}")
    return True
