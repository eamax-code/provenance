"""People: executive pay and pay versus performance (D-10), trading plans and proposed sales
(D-11, D-12). Contracts: docs/contracts/executive-pay.md, docs/contracts/insider-plans.md.
Information, not signals. Not investment advice."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader
from app.api.routes_companies import _ERRORS, _parse_cik_param, _require_company
from app.services import executive_pay, insider_plans

router = APIRouter(prefix="/v1/companies", tags=["companies"])


@router.get(
    "/{cik}/executive-pay",
    responses=_ERRORS,
    summary="Pay versus performance as disclosed in the proxy: PEO and average of the other "
    "named executives, TSR, peer TSR, net income and the company-selected measure",
)
def get_executive_pay(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Only proxies filed by this date"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    """As disclosed in the proxy's tagged pay-versus-performance table (Item 402(v)). The
    Summary Compensation Table is not tagged, so there is no per-executive row."""
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    return executive_pay.for_company(db, cik, as_of)


@router.get(
    "/{cik}/insider-plans",
    responses=_ERRORS,
    summary="Rule 10b5-1 and other trading plans (Item 408(a)) and Form 144 proposed sales, "
    "each joined to the Form 4 that followed",
)
def get_insider_plans(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Only filings filed by this date"),
    since: date | None = Query(None, description="Items dated on or after (default: 2 years)"),
    limit: int = Query(50, ge=1, le=200, description="Per list"),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    """Information, not signals. Not investment advice. The Form 4 join rule is in `notes`."""
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    return insider_plans.for_company(db, cik, since, as_of, limit)


@router.get(
    "/{cik}/corporate-tree",
    responses=_ERRORS,
    summary="GLEIF parents or reporting exceptions, GLEIF children, and exhibit 21 subsidiaries "
    "with their LEIs",
)
def get_corporate_tree(
    cik: str = Path(max_length=13),
    children_limit: int = Query(100, ge=1, le=500),
    subsidiaries_limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    """Parents and children from GLEIF Level 2 (golden copy, CC0; named, not linked);
    subsidiaries from the latest exhibit 21, each linking its filing."""
    from app.services import corporate_tree

    cik = _parse_cik_param(cik)
    company = _require_company(db, cik)
    return corporate_tree.for_company(db, company, children_limit, subsidiaries_limit)


@router.get(
    "/{cik}/comment-letters",
    responses=_ERRORS,
    summary="SEC comment letters and the company's responses, grouped by review, with topics",
)
def get_comment_letters(
    cik: str = Path(max_length=13),
    since: date | None = Query(None, description="Threads with a letter on or after this date"),
    topic: str | None = Query(None, max_length=40, description="One topic key"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
) -> dict:
    """Topics are tagged from a reviewed keyword list, never a model. Each letter links its
    filing; the letters' text is not returned."""
    from app.core.errors import APIError
    from app.services import comment_letters

    if topic and topic not in comment_letters.TOPIC_LABELS:
        keys = ", ".join(comment_letters.TOPIC_LABELS)
        raise APIError(422, "invalid_parameter", f"topic must be one of: {keys}")
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    return comment_letters.for_company(db, cik, since, topic, limit)
