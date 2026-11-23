"""X-14: what changed in an annual report's risk factors and MD&A against the previous one
(docs/contracts/changes.md). Stored data only."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.core.errors import APIError
from app.db.models import Filing
from app.services import tenk_sections

router = APIRouter(tags=["companies"])


def _answer(db: Session, f: Filing) -> dict:
    try:
        return tenk_sections.changes(db, f)
    except tenk_sections.NotAvailable as exc:
        raise APIError(404, "changes_not_available", exc.message,
                       details={"reason": exc.reason}) from exc  # fmt: skip


@router.get(
    "/v1/filings/{accession}/changes",
    responses=_ERRORS,
    summary="Risk factors and MD&A headings added, removed and reworded against the previous "
    "annual report",
)
def get_filing_changes(
    accession: str = Path(pattern=r"^\d{10}-\d{2}-\d{6}$"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    f = db.scalar(select(Filing).where(Filing.accession_number == accession).limit(1))
    if f is None:
        raise APIError(404, "filing_not_found", "No filing with this accession number.")
    return _answer(db, f)


@router.get(
    "/v1/companies/{cik}/changes",
    responses=_ERRORS,
    summary="What changed in the latest annual report's risk factors and MD&A",
)
def get_company_changes(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="The latest annual report filed by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    latest = tenk_sections.annual_reports(db, cik, as_of, limit=1)
    if not latest:
        raise APIError(404, "changes_not_available", "No annual report on file.",
                       details={"reason": "no_annual_report"})  # fmt: skip
    return _answer(db, latest[0])
