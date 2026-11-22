"""Segment labels as each company wrote them (launch plan E-4b).

The Notes data sets give segment members by name only ("IPhone", "MicrosoftThreeSixFive...").
Each filing's label linkbase (`*_lab.xml`, listed in its filing index) holds the company's own
labels: a terse label ("iPhone") and a standard one ("iPhone [Member]"). For every annual report
with segments, the linkbase is read once through the shared SEC limiter (filed documents are
cached and never fetched twice), and each member takes its terse label, else its standard label
without the " [Member]" suffix. Members the company did not label itself (US-GAAP standard members
such as ServiceMember) keep the label made from the member name; `label_source` says which.
No casing is guessed in code.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import CompanySegment
from app.services.insiders import safe_xml
from app.services.sec_client import SecClient, SecClientError, filing_index_url

XLINK = "{http://www.w3.org/1999/xlink}"
TERSE = "http://www.xbrl.org/2003/role/terseLabel"
STANDARD = "http://www.xbrl.org/2003/role/label"
_LAB_HREF = re.compile(r'href="(/Archives/edgar/data/[^"]+_lab\.xml)"', re.I)
_XSD_HREF = re.compile(r'href="(/Archives/edgar/data/[^"]+\.xsd)"', re.I)


def lab_url(index_html: str) -> str | None:
    """The label linkbase; newer inline XBRL filings embed it in the extension schema (.xsd)."""
    m = _LAB_HREF.search(index_html or "") or _XSD_HREF.search(index_html or "")
    return "https://www.sec.gov" + m.group(1) if m else None


def parse_labels(xml: str) -> dict[str, str]:
    """{member local name without "Member": label} for every member the linkbase labels."""
    root = safe_xml(xml)
    locs: dict[str, str] = {}  # loc label -> concept local name
    resources: dict[str, dict[str, str]] = {}  # label resource label -> {role: text}
    arcs: list[tuple[str, str]] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "loc":
            href = el.get(f"{XLINK}href") or ""
            concept = href.rsplit("#", 1)[-1]
            locs[el.get(f"{XLINK}label") or ""] = concept.split("_", 1)[-1]
        elif tag == "label":
            text = " ".join((el.text or "").split())
            if text:
                resources.setdefault(el.get(f"{XLINK}label") or "", {})[
                    el.get(f"{XLINK}role") or STANDARD
                ] = text
        elif tag == "labelArc":
            arcs.append((el.get(f"{XLINK}from") or "", el.get(f"{XLINK}to") or ""))
    out: dict[str, str] = {}
    for frm, to in arcs:
        concept = locs.get(frm)
        roles = resources.get(to)
        if not concept or not roles or not concept.endswith("Member"):
            continue
        text = roles.get(TERSE) or re.sub(r"\s*\[Member\]\s*$", "", roles.get(STANDARD, ""))
        if text:
            out[concept[: -len("Member")]] = text
    return out


def _member_name(key: str) -> str:
    """'BusinessSegments=IPhone' -> 'IPhone' (the part a label applies to)."""
    head = key.split(";", 1)[0]
    return head.split("=", 1)[-1]


def apply_filing(db: Session, sec: SecClient, cik: str, accession: str) -> int:
    """Label one filing's segment rows from its linkbase. Returns rows relabelled."""
    try:
        url = lab_url(sec.get_text(filing_index_url(cik, accession)).data)
        if url is None:
            return 0
        labels = parse_labels(sec.get_text(url).data)
    except (SecClientError, ValueError, ElementTree.ParseError):
        return 0
    n = 0
    rows = db.execute(
        select(CompanySegment.member).where(
            CompanySegment.accession_number == accession, CompanySegment.role != "consolidated"
        ).distinct()
    ).scalars()  # fmt: skip
    for member in list(rows):
        name = _member_name(member)
        text = labels.get(name) or labels.get(name.removesuffix("Segment"))
        if not text:
            continue
        if ";ConsolidationItems=" in member:  # a segment's own eliminations
            items = member.split("ConsolidationItems=", 1)[1]
            text = f"{text}: {labels.get(items) or 'intersegment eliminations'}"
        n += db.execute(
            update(CompanySegment)
            .where(CompanySegment.accession_number == accession,
                   CompanySegment.member == member)
            .values(label=text, label_source="filing_label")
        ).rowcount  # fmt: skip
    db.commit()
    return n
