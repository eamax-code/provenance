"""Companies going public, stage by stage, from their filings (ADR 0012)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.core.errors import APIError
from app.db.models import utcnow
from app.schemas.common import PageMeta
from app.schemas.graph import IpoList, IpoOut
from app.services import ipo_pipeline, ipo_terms

router = APIRouter(prefix="/v1", tags=["ipos"])


@router.get(
    "/ipos",
    response_model=IpoList,
    summary="Companies going public: registration, effectiveness, listing and pricing",
    description=(
        "First-time registrants with a going-public filing in the window, newest activity first. "
        "Stages: confidential (DRS), filed (S-1, F-1, or Form 10 for a spin-off), amended, "
        "effective (EFFECT), listing (8-A12B/8-A12G, CERT), priced (424B4), withdrawn (RW). "
        "Each milestone links its filing. EDGAR is read every hour, so a filing appears here "
        "within about an hour of acceptance."
    ),
)
def list_ipos(
    days: int = Query(90, ge=1, le=730, description="Activity in the last N days"),
    since: date | None = Query(None, description="Activity on or after this date; overrides days"),
    stage: str | None = Query(None, description="One of " + ", ".join(ipo_pipeline.STAGES)),
    kind: str | None = Query(None, description="ipo or spin_off"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    if stage and stage not in ipo_pipeline.STAGES:
        stages = ", ".join(ipo_pipeline.STAGES)
        raise APIError(400, "invalid_stage", f"stage must be one of {stages}")
    if kind and kind not in ("ipo", "spin_off"):
        raise APIError(400, "invalid_kind", "kind must be ipo or spin_off")
    start = since or (utcnow().date() - timedelta(days=days))
    rows = ipo_pipeline.companies(db, start, stage=stage)
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    page = rows[offset : offset + limit]
    more = offset + limit < len(rows)
    terms = ipo_terms.terms_by_cik(db, [r["cik"] for r in page])
    return IpoList(
        data=[IpoOut(**r, terms=terms.get(r["cik"])) for r in page],
        meta=PageMeta(limit=limit, offset=offset, has_more=more,
                      next_offset=offset + limit if more else None, total_matched=len(rows)),
    )  # fmt: skip
