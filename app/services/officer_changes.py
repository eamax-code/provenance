"""Officer and director changes read from 8-K item 5.02.

The filing's item 5.02 section is fetched once from EDGAR and stored. The local language model
lists each change (who, role, what, when, why, successor) with one sentence copied from the text
as evidence. Every row is checked against the stored text: a person whose name is not in the
text is dropped, and a row whose evidence or effective date is not found verbatim is kept but
marked unverified. Answers show the evidence and link the filing.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Filing, FilingSection, OfficerChange
from app.services.form8k import LEADERSHIP_ITEM
from app.services.llm import LLMUnavailable
from app.services.sec_client import SecClient, SecClientError

logger = logging.getLogger("app.officer_changes")

EXTRACTOR_VERSION = "1.3.0"
MAX_SECTION_CHARS = 8000
CHANGE_TYPES = [
    "departure",
    "retirement",
    "not_standing_for_reelection",
    "appointment",
    "election",
    "role_change",
    "compensation",
    "other",
]
CHANGE_LABELS = {
    "departure": "is leaving",
    "retirement": "is retiring",
    "not_standing_for_reelection": "will not stand for re-election",
    "appointment": "appointed",
    "election": "elected",
    "role_change": "changes role",
    "compensation": "pay or plan change",
    "other": "other change",
}

EXTRACT_PROMPT = """You read the Item 5.02 section of an SEC Form 8-K and list every change of a
director or officer it reports, ONE entry per person. Use only the TEXT.
- person: the full name as written (empty only for a company-wide plan or pay change).
- role: the title or board seat as written, e.g. "Executive Vice President, Business Development".
  Committee seats of a new director go in the same entry's role, never in a separate entry.
- change: one of departure, retirement, not_standing_for_reelection, appointment, election,
  role_change, compensation, other. A pay award, bonus, equity grant or employment agreement
  for a named officer is "compensation" for that person.
- what: the change in at most 20 words, with any amounts exactly as in the TEXT, e.g.
  "granted 96,000,000 restricted shares as an interim award" or "becomes Chief Financial Officer".
- effective: when the change takes effect, as written in the TEXT (e.g. "May 13, 2026",
  "immediately", "the 2026 annual meeting"). NOT the date the company was told or the filing
  date. "" if the TEXT does not say.
- reason: the stated reason in at most 10 words from the TEXT, e.g. "personal reasons" or
  "no disagreement with the company", or "".
- successor: the successor's name if the TEXT names one, or "".
- evidence: ONE sentence copied exactly from the TEXT that states the change.
Never invent names, titles or dates. Return {"changes": []} if no change is reported."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person": {"type": "string"},
                    "role": {"type": "string"},
                    "change": {"type": "string", "enum": CHANGE_TYPES},
                    "what": {"type": "string"},
                    "effective": {"type": "string"},
                    "reason": {"type": "string"},
                    "successor": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": [
                    "person",
                    "role",
                    "change",
                    "what",
                    "effective",
                    "reason",
                    "successor",
                    "evidence",
                ],
            },
        }
    },
    "required": ["changes"],
}

_ITEM_HEAD = re.compile(r"\bitem\s*(\d{1,2}\.\d{2})\b", re.IGNORECASE)
_END = re.compile(r"\bSIGNATURES?\b")
_SUFFIX = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "ph.d.", "md", "m.d."}


def document_url(f: Filing) -> str | None:
    if not f.primary_document:
        return None
    acc = f.accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(f.cik)}/{acc}/{f.primary_document}"


def html_to_text(doc: str) -> str:
    t = re.sub(r"(?is)<(script|style|ix:header)\b.*?</\1>", " ", doc)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[\xa0\u2002-\u200a\u202f]", " ", html.unescape(t))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def item_section(text: str, item: str = LEADERSHIP_ITEM) -> str | None:
    """The text under an item heading, up to the next item or the signature block.

    A cover page or contents list may name the item too, so the longest candidate wins."""
    best = ""
    for m in _ITEM_HEAD.finditer(text):
        if m.group(1) != item:
            continue
        start = m.start()
        nxt = next((n for n in _ITEM_HEAD.finditer(text, m.end()) if n.group(1) != item), None)
        end_sig = _END.search(text, m.end())
        stops = [x.start() for x in (nxt, end_sig) if x is not None]
        chunk = text[start : min(stops) if stops else len(text)].strip()
        if len(chunk) > len(best):
            best = chunk
    return best[:MAX_SECTION_CHARS] if len(best) > 40 else None


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def _surname(person: str) -> str:
    parts = [p for p in re.split(r"[\s,]+", person.strip()) if p]
    while parts and parts[-1].lower() in _SUFFIX:
        parts.pop()
    return parts[-1] if parts else ""


def verify(change: dict, section: str) -> tuple[bool, bool]:
    """(keep, verified): drop a person who is not in the text; verify evidence and date."""
    text = _norm(section)
    person = (change.get("person") or "").strip()
    if person and _norm(_surname(person)) not in text:
        return False, False
    if not person and change.get("change") != "compensation":
        return False, False
    effective = change.get("effective") or ""
    ok = source_sentence(change.get("evidence") or "", section) is not None
    return True, ok and _date_in_text(effective, text)


def _sentences(section: str) -> list[str]:
    flat = re.sub(r"\s+", " ", section)
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z(\u201c\"])", flat) if x.strip()]


def source_sentence(evidence: str, section: str) -> str | None:
    """The filing sentence the model's quote came from: the one holding nearly all of its words
    and every one of its figures. Small models shorten quotes; the answer shows the original."""
    want = re.findall(r"[a-z0-9]{3,}", _norm(evidence))
    if len(want) < 4:
        return None
    figures = set(re.findall(r"\d[\d,.]*\d|\d", _norm(evidence)))
    best, best_score = None, 0.0
    for sent in _sentences(section):
        have = set(re.findall(r"[a-z0-9]{3,}", _norm(sent)))
        score = sum(w in have for w in want) / len(want)
        if score > best_score and figures <= set(re.findall(r"\d[\d,.]*\d|\d", _norm(sent))):
            best, best_score = sent, score
    return best if best_score >= 0.85 else None


def _date_in_text(value: str, text: str) -> bool:
    """An effective date counts as found if the text has it as written or in long form; a
    phrase such as "the 2026 annual meeting" if each of its words is in the text."""
    if not value.strip():
        return True
    if _norm(value) in text:
        return True
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            d = datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
        return any(_norm(v) in text for v in _date_forms(d))
    words = set(re.findall(r"[a-z0-9]+", text))
    return all(w in words for w in re.findall(r"[a-z0-9]+", _norm(value)))


def numbers_in_text(phrase: str, text: str) -> bool:
    """Every figure in a model-written phrase must appear in the filing text."""
    have = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    return all(n.replace(",", "") in have for n in re.findall(r"\d[\d,]*(?:\.\d+)?", phrase))


def _date_forms(d: date) -> list[str]:
    return [d.isoformat(), f"{d:%B} {d.day}, {d.year}", f"{d:%b}. {d.day}, {d.year}"]


def _fetch_section(db: Session, sec: SecClient, f: Filing) -> FilingSection:
    url = document_url(f)
    row = FilingSection(
        cik=f.cik,
        accession_number=f.accession_number,
        item=LEADERSHIP_ITEM,
        source_url=url or f.source_url,
        status="fetch_failed",
        fetched_at=datetime.now(UTC),
    )
    if url:
        try:
            doc = sec.get_text(url).data
            section = item_section(html_to_text(doc))
            row.status, row.text = ("ok", section) if section else ("no_section", None)
        except SecClientError as exc:
            log_event(logger, logging.WARNING, "8-K fetch failed", url=url, error=str(exc))
    db.add(row)
    db.flush()
    return row


def _extract(db: Session, llm, f: Filing, row: FilingSection) -> None:
    reply = llm.chat(
        [
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"TEXT:\n{row.text}"},
        ],
        schema=EXTRACT_SCHEMA,
        max_tokens=900,
        temperature=0.0,
    )
    db.execute(delete(OfficerChange).where(OfficerChange.accession_number == f.accession_number))
    row.extractor_version, row.model = EXTRACTOR_VERSION, reply.model
    row.extracted_at = datetime.now(UTC)
    try:
        changes = json.loads(reply.text).get("changes") or []
    except (ValueError, AttributeError):
        row.extraction_status = "failed"
        return
    seq = 0
    seen: set[str] = set()
    for c in changes:
        if not isinstance(c, dict) or c.get("change") not in CHANGE_TYPES:
            continue
        who = _norm(c.get("person") or "")
        if who and who in seen:
            continue  # one entry per person; small models split committee seats out
        seen.add(who)
        keep, ok = verify(c, row.text or "")
        if not keep:
            continue
        what = (c.get("what") or "").strip()
        seq += 1
        db.add(
            OfficerChange(
                cik=f.cik,
                accession_number=f.accession_number,
                filing_date=f.filing_date,
                seq=seq,
                person=(c.get("person") or "").strip() or None,
                role=(c.get("role") or "").strip() or None,
                change_type=c["change"],
                what=what if what and numbers_in_text(what, row.text or "") else None,
                effective=(c.get("effective") or "").strip() or None,
                reason=(c.get("reason") or "").strip() or None,
                successor=(c.get("successor") or "").strip() or None,
                evidence=source_sentence(c.get("evidence") or "", row.text or "")
                or (c.get("evidence") or "").strip()
                or None,
                verified=ok,
                source_url=row.source_url,
                extractor_version=EXTRACTOR_VERSION,
                model=reply.model,
            )
        )
    row.extraction_status = "ok"


def ensure_extracted(db: Session, filings: Iterable[Filing], *, sec: SecClient | None, llm) -> dict:
    """Fetch and read the given 5.02 filings that have not been read yet. Commits per filing.

    With `sec` None nothing is fetched; with `llm` None nothing new is extracted."""
    summary = {"fetched": 0, "extracted": 0, "failed": 0}
    for f in filings:
        row = db.scalar(
            select(FilingSection).where(
                FilingSection.accession_number == f.accession_number,
                FilingSection.item == LEADERSHIP_ITEM,
            )
        )
        if row is None:
            if sec is None:
                continue
            row = _fetch_section(db, sec, f)
            summary["fetched"] += 1
            db.commit()
        if row.status != "ok" or row.extractor_version == EXTRACTOR_VERSION or llm is None:
            continue
        try:
            _extract(db, llm, f, row)
            attach_context(db, f.accession_number)
            db.commit()
            summary["extracted"] += 1
            from app.services.events import publish_pending

            publish_pending(db)  # after the commit: the feed never runs ahead of visible rows
        except LLMUnavailable:
            db.rollback()
            summary["failed"] += 1
            break  # the model is down; later filings would fail the same way
    return summary


def attach_context(db: Session, accession_number: str) -> None:
    """Company and peer figures as filed by the filing date, on each change of the filing."""
    from app.services.leadership_context import context_for

    for c in db.scalars(
        select(OfficerChange).where(OfficerChange.accession_number == accession_number)
    ):
        ctx = context_for(db, c)
        c.context = json.dumps(ctx) if ctx else None


def changes_by_accession(db: Session, accessions: list[str]) -> dict[str, dict]:
    """Stored reading per filing: {"status", "changes": [OfficerChange...]}."""
    if not accessions:
        return {}
    out: dict[str, dict] = {}
    for row in db.scalars(
        select(FilingSection).where(
            FilingSection.accession_number.in_(accessions),
            FilingSection.item == LEADERSHIP_ITEM,
        )
    ):
        out[row.accession_number] = {
            "status": row.extraction_status or row.status,
            "changes": [],
        }
    for c in db.scalars(
        select(OfficerChange)
        .where(OfficerChange.accession_number.in_(accessions))
        .order_by(OfficerChange.accession_number, OfficerChange.seq)
    ):
        out.setdefault(c.accession_number, {"status": "ok", "changes": []})["changes"].append(c)
    return out


def change_dict(c: OfficerChange) -> dict:
    return {
        "person": c.person,
        "role": c.role,
        "change": c.change_type,
        "change_label": CHANGE_LABELS.get(c.change_type, c.change_type),
        "what": c.what,
        "effective": c.effective,
        "reason": c.reason,
        "successor": c.successor,
        "evidence": c.evidence,
        "verified": c.verified,
        "sentence": describe(c),
        "context": json.loads(c.context) if c.context else None,
    }


def describe(c: OfficerChange) -> str:
    """One plain sentence for an answer, built only from the stored fields."""
    who = c.person or "The company"
    role = c.role or ""
    if c.change_type == "compensation" and not c.person and c.evidence:
        return c.evidence.rstrip(".") + "."
    if c.change_type in ("appointment", "election"):
        to = (
            "to the Board of Directors"
            if "board" in role.lower() and "chair" not in role.lower()
            else (f"as {role}" if role else "")
        )
        line = f"{who} {'appointed' if c.change_type == 'appointment' else 'elected'} {to}"
    elif c.change_type in ("compensation", "role_change", "other") and c.what:
        line = f"{who}, {role}: {c.what}" if role else f"{who}: {c.what}"
    elif c.change_type == "role_change":
        line = f"{who} moves to {role}" if role else f"{who} changes role"
    else:
        line = f"{who}, {role}," if role else who
        line += " " + CHANGE_LABELS.get(c.change_type, "other change")
    line = line.rstrip(", ")
    if c.effective and c.effective.lower() not in line.lower():
        line += f", effective {c.effective}"
    if c.reason:
        line += f". Reason given: {c.reason}"
    if c.successor and c.successor not in line:
        joining = c.change_type in ("appointment", "election", "role_change")
        line += f". {'Replaces' if joining else 'Successor'}: {c.successor}"
    return line.rstrip(".") + "."
