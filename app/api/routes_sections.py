"""Q-09: a 10-K item's text as filed (docs/contracts/sections.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS
from app.core.errors import APIError
from app.db.models import Filing
from app.services import sections
from app.services.notes import with_detail

router = APIRouter(tags=["companies"])  # beside /v1/filings/{accession}/changes
_ACC = Path(pattern=r"^\d{10}-\d{2}-\d{6}$", description="e.g. 0000320193-26-000026")


def _filing(db: Session, accession: str) -> Filing:
    f = db.scalar(select(Filing).where(Filing.accession_number == accession))
    if f is None:
        raise APIError(404, "filing_not_found", "No filing with this accession number is stored.")
    return f


@router.get(
    "/v1/filings/{accession}/sections",
    responses=_ERRORS,
    summary="The 10-K items held for one filing",
    description="Items 1A (Risk Factors) and 7 (MD&A) of the latest two 10-Ks for the companies "
    "read; other items are not read yet. coverage says so on every response.",
)
def filing_sections(
    accession: str = _ACC, db: Session = Depends(db_session), _key=Depends(require_reader)
) -> dict:
    return sections.items(db, _filing(db, accession))


@router.get(
    "/v1/filings/{accession}/sections/{item}",
    responses=_ERRORS,
    summary="A 10-K item's text as filed, with its heading, document link and offsets",
    description="The item as filed (never summarised): its heading, the text, subheadings as "
    "offsets, the primary document on EDGAR Archives and where the text sits in the document's "
    "text as read (its paragraphs joined by a blank line). Items 1A and 7 only.",
)
def filing_section(
    accession: str = _ACC,
    item: str = Path(pattern="^(1A|7)$"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    f = _filing(db, accession)
    out = sections.item(db, f, item)
    if out is None:
        held = sections.items(db, f)["items"]
        which = ", ".join(i["item"] for i in held) or "none"
        raise APIError(
            404,
            "section_not_held",
            f"Item {item} is not held for this filing (held: {which}). {sections.coverage(db)}",
        )
    return with_detail(out)
