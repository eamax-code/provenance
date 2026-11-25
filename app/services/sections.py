"""Q-09: a 10-K item's text as filed, with its heading, the Archives document and its offsets in
the document's text as read (docs/contracts/sections.md). Never summarised."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, FilingSection
from app.services.sec_client import filing_index_url
from app.services.tenk_sections import ITEMS

TITLES = {"1A": "Risk Factors", "7": "Management's Discussion and Analysis"}
BASIS = (
    "characters in the document's text as read: its paragraphs, in order, joined by a blank line"
)
NOTE = "Text as filed, from the document linked; never summarised."


def coverage(db: Session) -> str:
    n = db.scalar(
        select(func.count(func.distinct(FilingSection.cik))).where(
            FilingSection.item.in_(list(ITEMS.values())), FilingSection.filed_text.is_not(None)
        )
    )
    about = max(10, round((n or 0), -1))
    return (
        f"Items 1A and 7 of the latest two 10-Ks for about {about} companies are held; other "
        "items are not read yet."
    )


def _held(db: Session, accession: str) -> dict[str, FilingSection]:
    rows = db.scalars(
        select(FilingSection).where(
            FilingSection.accession_number == accession,
            FilingSection.item.in_(list(ITEMS.values())),
            FilingSection.filed_text.is_not(None),
        )
    )
    return {r.item.split(":")[1]: r for r in rows}


def _filing(f: Filing) -> dict:
    return {
        "accession_number": f.accession_number,
        "cik": f.cik,
        "form": f.form_type,
        "filed_date": f.filing_date.isoformat() if f.filing_date else None,
        "report_date": f.report_date.isoformat() if f.report_date else None,
    }


def items(db: Session, f: Filing) -> dict:
    held = _held(db, f.accession_number)
    return {
        **_filing(f),
        "items": [
            {"item": k, "title": TITLES[k], "characters": len(held[k].filed_text)}
            for k in ITEMS
            if k in held
        ],
        "coverage": coverage(db),
    }


def item(db: Session, f: Filing, key: str) -> dict | None:
    """The item, or None when it is not held for this filing."""
    s = _held(db, f.accession_number).get(key)
    if s is None:
        return None
    lay = json.loads(s.layout)
    company = db.scalar(select(Company.legal_name).where(Company.cik == f.cik))
    return {
        **_filing(f),
        "company": company,
        "item": key,
        "title": TITLES[key],
        "heading": lay["heading"],
        "text": s.filed_text,
        "subheadings": [{"group": bool(g), "start": a, "end": b} for a, b, g in lay["subheadings"]],
        "document": {"url": s.source_url, "name": lay.get("document")},
        "filing_url": filing_index_url(f.cik, f.accession_number),
        "offsets": {"start": lay["start"], "end": lay["end"], "basis": BASIS},
        "coverage": coverage(db),
        "notes": [NOTE],
    }
