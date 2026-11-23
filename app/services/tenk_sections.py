"""Risk factors (Item 1A) and MD&A (Item 7) of annual reports, heading by heading, and what
changed against the previous year (X-14, docs/contracts/changes.md).

The 10-K items are not in the SEC's structured data. Each annual report in the read set is
fetched once through the SEC client, its two items are cut out of the HTML and stored as
sections `10k:1A` and `10k:7` (plain text; a heading is a line starting "## ", a group heading
"# "). Both years of a comparison are read from the stored text with the same splitter; when
either year does not split into headings, there is no comparison (a half-diff misleads).

A heading is a paragraph set (almost) entirely in bold or italics. Matching: identical after
normalising is unchanged; otherwise each heading pairs with its most similar counterpart and a
pair at or above THRESHOLD is reworded; the rest is added or removed. Similarity is the larger
of the token-set Jaccard of the heading plus its first 400 characters, and 0.9 times the share
of the shorter heading's distinctive words (generic risk-factor words left out) found in the
other.
"""

from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser

ITEMS = {"1A": "10k:1A", "7": "10k:7"}
FORMS = ("10-K", "10-K405", "10-KT")
THRESHOLD = 0.6
MIN_HEADINGS = 3  # fewer than this and the item did not split: no comparison
TEXT_CHARS = 1500
MAX_SECTION_CHARS = 400_000

_BLOCK = {"p", "div", "tr", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table", "td"}
_BOLD = re.compile(r"font-weight\s*:\s*(bold|bolder|[6-9]00)", re.I)
_ITALIC = re.compile(r"font-style\s*:\s*italic", re.I)
_GROUP = re.compile(
    r"^(?:risks?|summary of risk factors|general risk factors|other risks)\b.{0,140}$"
    r"|^.{0,140}\brisks?$",
    re.I,
)  # fmt: skip
_START = {
    "1A": re.compile(r"^item\s*1a\.?\s*[:.\-—–]?\s*risk\s+factors\.?$", re.I),
    "7": re.compile(r"^item\s*7\.?\s*[:.\-—–]?\s*management.s\s+discussion\b.*$", re.I),
}
_BARE = {"1A": re.compile(r"^item\s*1a\.?:?$", re.I), "7": re.compile(r"^item\s*7\.?:?$", re.I)}
_TITLE = {"1A": re.compile(r"^risk\s+factors\.?$", re.I),
          "7": re.compile(r"^management.s\s+discussion\b", re.I)}  # fmt: skip
_END = {
    "1A": re.compile(r"^item\s*(1b|1c|2)\b", re.I),
    "7": re.compile(r"^item\s*(7a|8)\b", re.I),
}
_NOISE = re.compile(r"^(table of contents|\d{1,3}|page \d+|[ivx]{1,5})$", re.I)


class _Paragraphs(HTMLParser):
    """Paragraphs of an HTML document with the share of their characters in bold or italics."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[tuple[str, float]] = []
        self._stack: list[tuple[str, bool]] = []
        self._buf: list[tuple[str, bool]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "ix:header"):
            self._skip += 1
            return
        if tag in _BLOCK:
            self._flush()
        style = dict(attrs).get("style") or ""
        em = tag in ("b", "strong", "i", "em") or bool(_BOLD.search(style) or _ITALIC.search(style))
        self._stack.append((tag, em))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "ix:header"):
            self._skip = max(0, self._skip - 1)
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break
        if tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        self._buf.append((data, any(em for _, em in self._stack)))

    def _flush(self):
        text = " ".join("".join(d for d, _ in self._buf).replace(" ", " ").split())
        if text:
            total = sum(len(d.strip()) for d, _ in self._buf) or 1
            emph = sum(len(d.strip()) for d, e in self._buf if e)
            self.out.append((text, emph / total))
        self._buf = []

    def close(self):
        super().close()
        self._flush()


def paragraphs(doc: str) -> list[tuple[str, float]]:
    p = _Paragraphs()
    p.feed(html_lib.unescape(doc) if "<" not in doc[:2000] else doc)
    p.close()
    return [(t, e) for t, e in p.out if not _NOISE.match(t)]


def _region(paras: list[tuple[str, float]], item: str) -> list[tuple[str, float]]:
    """The item's paragraphs: from the start heading that has the longest run before the next
    item's heading (the table of contents has the shortest)."""
    best: list[tuple[str, float]] = []
    for i, (t, _) in enumerate(paras):
        if len(t) > 160:
            continue
        if not _START[item].match(t):
            # "Item 1A." and "Risk Factors" in two paragraphs (Amazon's layout)
            if not (_BARE[item].match(t) and i + 1 < len(paras)
                    and _TITLE[item].match(paras[i + 1][0])):  # fmt: skip
                continue
            i += 1
        j = i + 1
        while j < len(paras) and not (len(paras[j][0]) < 200 and _END[item].match(paras[j][0])):
            j += 1
        if j - i > len(best):
            best = paras[i + 1 : j]
    return best


def _is_heading(text: str, emph: float, item: str = "1A") -> bool:
    shortest = 12 if item == "1A" else 4  # MD&A sub-headings are short ("Overview", "Liquidity")
    return emph >= 0.9 and shortest <= len(text) <= 700 and not text.lower().startswith("item ")


_PRONOUN = re.compile(r"\b(we|our|us|it|its|the company|could|may|might|can|will)\b", re.I)


def _is_group(text: str) -> bool:
    """'Business and Industry Risks', 'Risks Related to Our Business' are groups; 'Our
    International Operations Expose Us to a Number of Risks' is a risk."""
    if not _GROUP.match(text) or len(text.split()) > 9:
        return False
    rest = re.sub(r"(?i)^risks?\s+(related|relating)\s+to\s+", "", text)
    return not _PRONOUN.search(rest) or rest != text and len(rest.split()) <= 5


def section_text(doc: str, item: str) -> str | None:
    """The stored form of one item: '# group', '## heading' and body lines. None when the item
    is not found."""
    region = _region(paragraphs(doc), item)
    if not region:
        return None
    lines: list[str] = []
    for t, e in region:
        if _is_heading(t, e, item):
            prev = lines[-1] if lines else ""
            # a heading the layout broke over two paragraphs: "...ensure every airplane" /
            # "achieve planned production rate targets, ..."
            if prev.startswith("## ") and not prev.rstrip().endswith((".", "?", "!", ":")) \
                    and t[:1].islower():  # fmt: skip
                lines[-1] = prev + " " + t
                continue
            lines.append(("# " if item == "1A" and _is_group(t) else "## ") + t)
        else:
            lines.append(t)
    return "\n".join(lines)[:MAX_SECTION_CHARS]


def headings(text: str | None) -> list[dict]:
    """[{heading, group, text}] from a stored section."""
    out: list[dict] = []
    group = None
    for line in (text or "").split("\n"):
        if line.startswith("# "):
            group = line[2:].strip()
        elif line.startswith("## "):
            out.append({"heading": line[3:].strip(), "group": group, "text": ""})
        elif out:
            out[-1]["text"] = (out[-1]["text"] + " " + line).strip()
    return out


def _norm(h: str) -> str:
    h = re.sub(r"^[\s\d.()•\-–—]+", "", h.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", h).split())


_WORD = re.compile(r"[a-z0-9]+")


_GENERIC = set("""a an and are as at be been by can could do for from has have in including
into is it its may might not of on or our such that the their these this to was we were which
will with would company company s companies business businesses results operations operating
financial condition adversely adverse affect affected affects materially material significant
significantly harm risk risks result impact impacted subject time""".split())  # fmt: skip


def _tokens(h: dict) -> set[str]:
    return set(_WORD.findall((h["heading"] + " " + h["text"][:400]).lower()))


def _head_words(h: dict) -> set[str]:
    return set(_WORD.findall(h["heading"].lower())) - _GENERIC


def _similarity(a: dict, b: dict, ta: set, tb: set) -> float:
    """The larger of the token-set Jaccard (heading plus 400 characters) and the share of the
    shorter heading's distinctive words found in the other heading (a heading that grew by a
    clause is still the same risk)."""
    ha, hb = _head_words(a), _head_words(b)
    overlap = len(ha & hb) / min(len(ha), len(hb)) if len(ha) >= 4 and len(hb) >= 4 else 0.0
    return max(_jaccard(ta, tb), overlap * 0.9)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _brief(h: dict) -> dict:
    return {"heading": h["heading"], "group": h["group"], "text": h["text"][:TEXT_CHARS],
            "text_length": len(h["text"])}  # fmt: skip


def diff(now: list[dict], before: list[dict]) -> dict:
    """added, removed, reworded and counts between two lists of headings."""
    before_by = {}
    for h in before:
        before_by.setdefault(_norm(h["heading"]), h)
    used = set()
    unchanged, rest_now = 0, []
    for h in now:
        k = _norm(h["heading"])
        if k in before_by and k not in used:
            used.add(k)
            unchanged += 1
        else:
            rest_now.append(h)
    rest_before = [h for h in before if _norm(h["heading"]) not in used]
    pairs = []
    tn = [_tokens(h) for h in rest_now]
    tb = [_tokens(h) for h in rest_before]
    for i in range(len(rest_now)):
        for j in range(len(rest_before)):
            s = _similarity(rest_now[i], rest_before[j], tn[i], tb[j])
            if s >= THRESHOLD:
                pairs.append((s, i, j))
    pairs.sort(reverse=True)
    taken_i, taken_j, reworded = set(), set(), []
    for s, i, j in pairs:
        if i in taken_i or j in taken_j:
            continue
        taken_i.add(i)
        taken_j.add(j)
        a, b = rest_now[i], rest_before[j]
        reworded.append({**_brief(a), "heading_before": b["heading"], "similarity": round(s, 2),
                         "text_before": b["text"][:TEXT_CHARS]})  # fmt: skip
    reworded.sort(key=lambda r: r["similarity"])
    added = [_brief(h) for i, h in enumerate(rest_now) if i not in taken_i]
    removed = [_brief(h) for j, h in enumerate(rest_before) if j not in taken_j]
    return {
        "counts": {"now": len(now), "before": len(before), "added": len(added),
                   "removed": len(removed), "reworded": len(reworded), "unchanged": unchanged},
        "added": added, "removed": removed, "reworded": reworded,
    }  # fmt: skip


# -- storage and comparison --------------------------------------------------------------

TITLES = {"10k:1A": "10-K item 1A: Risk factors", "10k:7": "10-K item 7: MD&A"}
EXTRACTOR = "tenk-1"
PRIOR_MIN_DAYS, PRIOR_MAX_DAYS = 270, 460  # the previous annual report: 9 to 15 months earlier


def _doc_url(f) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(f.cik)}/"
            f"{f.accession_number.replace('-', '')}/{f.primary_document}")  # fmt: skip


def read_filing(db, sec, f, refresh: bool = False) -> dict:
    """Fetch one annual report and store its two items (status ok or no_section). Already
    stored: nothing is fetched, unless refresh (the document then usually comes from the SEC
    client's cache of Archives documents)."""
    from sqlalchemy import delete, select

    from app.db.models import FilingSection, utcnow

    if refresh:
        db.execute(delete(FilingSection).where(
            FilingSection.accession_number == f.accession_number,
            FilingSection.item.in_(list(ITEMS.values()))))  # fmt: skip

    have = set(db.scalars(select(FilingSection.item).where(
        FilingSection.accession_number == f.accession_number,
        FilingSection.item.in_(list(ITEMS.values())))))  # fmt: skip
    if have >= set(ITEMS.values()):
        return {"accession_number": f.accession_number, "skipped": True}
    doc = sec.get_text(_doc_url(f)).data
    out = {"accession_number": f.accession_number}
    for item, key in ITEMS.items():
        if key in have:
            continue
        text = section_text(doc, item)
        n = len(headings(text))
        db.add(FilingSection(
            cik=f.cik, accession_number=f.accession_number, item=key,
            status="ok" if text else "no_section", text=text, source_url=_doc_url(f),
            fetched_at=utcnow(), extractor_version=EXTRACTOR,
            extraction_status="ok" if n >= MIN_HEADINGS else "no_headings",
        ))  # fmt: skip
        out[key] = n
    db.commit()
    return out


def annual_reports(db, cik: str, as_of=None, limit: int = 2) -> list:
    from sqlalchemy import select

    from app.db.models import Filing

    q = select(Filing).where(Filing.cik == cik, Filing.form_type.in_(FORMS),
                             Filing.primary_document.is_not(None))  # fmt: skip
    if as_of:
        q = q.where(Filing.filing_date <= as_of)
    return list(db.scalars(q.order_by(Filing.filing_date.desc()).limit(limit)))


def _prior(db, f):

    from sqlalchemy import select

    from app.db.models import Filing

    ref = f.report_date or f.filing_date
    rows = db.scalars(select(Filing).where(
        Filing.cik == f.cik, Filing.form_type.in_(FORMS), Filing.filing_date < f.filing_date,
    ).order_by(Filing.filing_date.desc()).limit(3))  # fmt: skip
    for p in rows:
        d = (ref - (p.report_date or p.filing_date)).days
        if PRIOR_MIN_DAYS <= d <= PRIOR_MAX_DAYS:
            return p
    return None


def _filing_dict(f) -> dict:
    return {"accession_number": f.accession_number, "form": f.form_type,
            "period": f.report_date.isoformat() if f.report_date else None,
            "filed_date": f.filing_date.isoformat(), "source_url": f.source_url}  # fmt: skip


def _stored(db, accession: str) -> dict:
    from sqlalchemy import select

    from app.db.models import FilingSection

    return {s.item: s for s in db.scalars(select(FilingSection).where(
        FilingSection.accession_number == accession,
        FilingSection.item.in_(list(ITEMS.values()))))}  # fmt: skip


METHOD = {
    "headings": "Risk factor headings are the bold or italic lead sentences in Item 1A; MD&A "
    "headings are its bold or italic sub-headings.",
    "matching": "A heading is unchanged when its normalized text is identical. Otherwise it "
    "is paired with the most similar heading on the other side; a pair at or above 0.60 "
    "similarity is reworded (the larger of the token-set Jaccard of heading plus first 400 "
    "characters, and 0.9 times the share of the shorter heading's distinctive words found in "
    "the other); anything left unpaired is added or removed.",
    "threshold": THRESHOLD,
}


class NotAvailable(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason, self.message = reason, message


def changes(db, f) -> dict:
    """The comparison for one annual report, or NotAvailable with the reason."""
    if f.form_type not in FORMS:
        raise NotAvailable("not_annual_report", "Changes are compared for 10-K annual reports.")
    now = _stored(db, f.accession_number)
    if "10k:1A" not in now:
        raise NotAvailable(
            "not_read",
            "This annual report is not in the set read for "
            "changes yet (the showcase companies and the largest filers).",
        )
    prior = _prior(db, f)
    before = _stored(db, prior.accession_number) if prior else {}
    if prior is not None and "10k:1A" not in before:
        raise NotAvailable("prior_not_read", "The previous annual report is not read yet.")

    def block(key):
        a = headings(now[key].text) if key in now else []
        if prior is None:
            return {"counts": {"now": len(a)}, "headings": [_brief(h) for h in a]}
        b = headings(before[key].text) if key in before else []
        if len(a) < MIN_HEADINGS or len(b) < MIN_HEADINGS:
            return None
        return diff(a, b)

    risk = block("10k:1A")
    if risk is None:
        raise NotAvailable(
            "not_split",
            "The risk factors of this report or the previous one "
            "did not split into headings, so there is no comparison.",
        )
    return {
        "filing": _filing_dict(f), "prior": _filing_dict(prior) if prior else None,
        "risk_factors": risk, "mdna": block("10k:7"), "method": METHOD,
    }  # fmt: skip


def available(db, accessions: list[str]) -> set[str]:
    """Which of these annual reports have a comparison to show (both years read and split)."""
    from sqlalchemy import select

    from app.db.models import FilingSection

    if not accessions:
        return set()
    from app.db.models import Filing

    def split_ok(accs):
        return set(db.scalars(select(FilingSection.accession_number).where(
            FilingSection.accession_number.in_(accs), FilingSection.item == "10k:1A",
            FilingSection.extraction_status == "ok")))  # fmt: skip

    out = set()
    for acc in split_ok(accessions):
        f = db.scalar(select(Filing).where(Filing.accession_number == acc).limit(1))
        p = _prior(db, f) if f is not None else None
        if p is not None and split_ok([p.accession_number]):
            out.add(acc)
    return out
