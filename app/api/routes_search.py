"""Search across companies, filing sections and company profiles (issue #3, step 3)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import Company, CompanyDocument, utcnow
from app.schemas.common import ErrorEnvelope
from app.services import documents, section_search, semantic_search
from app.services.company_lookup import search_companies
from app.services.public import showcase_ciks
from app.services.sec_client import company_filings_url, normalize_cik

router = APIRouter(prefix="/v1", tags=["search"])
_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
COMPANY_HITS = 5


class CompanyHit(BaseModel):
    cik: str
    legal_name: str
    ticker: str | None
    exchange: str | None
    match: str = Field(
        description="name (ticker, CIK or name lookup), former_name (a name it used before, in "
        "matched_name) or profile (profile text)"
    )
    matched_name: str | None = None
    filings_url: str


class SectionResult(BaseModel):
    cik: str
    company: str | None
    accession_number: str
    item: str
    title: str
    form_type: str | None
    filing_date: date | None
    source_url: str = Field(description="The filing's index page on sec.gov")
    score: float
    snippet: str


class SearchResult(BaseModel):
    query: str
    mode: str
    companies: list[CompanyHit]
    sections: list[SectionResult]
    notes: list[str]


class ProfileOut(BaseModel):
    cik: str
    name: str
    summary: str = Field(description="A few cited sentences; [n] refers to citations")
    citations: list[dict]
    markdown: str
    generated_at: datetime


@router.get(
    "/search",
    response_model=SearchResult,
    responses=_ERRORS,
    summary="Search companies and the text of their filings",
    description="Companies by name, ticker or CIK (and by the words of their profiles), plus "
    "passages from stored filing sections (prospectus sections, 8-K item 5.02, earnings "
    "releases). mode=keyword needs every word; mode=semantic finds passages by meaning (your "
    "own key only). Every passage links to its filing.",
)
def search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    cik: str | None = Query(None, max_length=13, description="Only this company's filings"),
    form: str | None = Query(None, max_length=20, description="Only this form, e.g. S-1"),
    as_of: date | None = Query(None, description="Only filings dated on or before this date"),
    mode: str = Query("keyword", pattern="^(keyword|semantic)$"),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    try:
        cik = normalize_cik(cik) if cik else None
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be numeric.") from exc
    notes: list[str] = []
    demo = getattr(request.state, "demo", False)
    allowed = set(showcase_ciks(db, settings)[0]) if demo else None
    if allowed is not None and cik and cik not in allowed:
        raise APIError(403, "demo_scope", "The demo key covers the public showcase companies only.")
    companies = [] if cik else _companies(db, q)
    if mode == "semantic":
        if demo:
            raise APIError(
                403,
                "semantic_needs_key",
                "Semantic search runs an embedding model; use your own API key, or mode=keyword.",
            )
        try:
            hits = semantic_search.search(
                db, settings, q, mode="vector", cik=cik, as_of=as_of, limit=limit
            )
            sections = [
                _section(h.cik, h.accession_number, h.item, h.title, h.form_type, h.filing_date,
                         h.source_url, h.score, h.text[:400])
                for h in hits
                if not form or (h.form_type or "").upper() == form.upper()
            ]  # fmt: skip
        except semantic_search.EmbeddingUnavailable:
            notes.append("The embedding model is unavailable; these are keyword results.")
            mode = "keyword"
    if mode == "keyword":
        hits = section_search.search_sections(
            db,
            q,
            cik=cik,
            forms=[form.upper()] if form else None,
            as_of=as_of,
            limit=limit if allowed is None else 50,
        )
        sections = [
            _section(h.cik, h.accession_number, h.item, h.title, h.form_type, h.filing_date,
                     h.source_url, h.rank, h.snippet)
            for h in hits
        ]  # fmt: skip
    if allowed is not None:
        sections = [s for s in sections if s.cik in allowed][:limit]
    names = dict(
        db.execute(
            select(Company.cik, Company.legal_name).where(
                Company.cik.in_({s.cik for s in sections})
            )
        ).all()
    )
    for s in sections:
        s.company = names.get(s.cik)
    notes.append(
        "Passages come from filing sections this service has read: prospectus sections for "
        "companies going public, 8-K item 5.02 and earnings releases. Annual report text is not "
        "searchable yet."
    )
    return SearchResult(query=q, mode=mode, companies=companies, sections=sections, notes=notes)


@router.get(
    "/companies/{cik}/profile",
    response_model=ProfileOut,
    responses=_ERRORS,
    summary="A readable profile of one company, every figure linked to its filing",
)
def profile(cik: str, db: Session = Depends(db_session), _key=Depends(require_reader)):
    try:
        cik = normalize_cik(cik)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be numeric.") from exc
    p = documents.build_profile(db, cik)
    if p is None:
        raise APIError(404, "company_not_found", "No company with this CIK is available.")
    return ProfileOut(
        cik=p.cik,
        name=p.name,
        summary=p.summary,
        citations=p.citations,
        markdown=p.markdown,
        generated_at=utcnow(),
    )


def _section(cik, accession, item, title, form, filed, url, score, snippet) -> SectionResult:
    return SectionResult(
        cik=cik,
        company=None,
        accession_number=accession,
        item=item,
        title=title,
        form_type=form,
        filing_date=filed,
        source_url=url,
        score=round(float(score), 4),
        snippet=" ".join(snippet.split()),
    )


def _companies(db: Session, q: str) -> list[CompanyHit]:
    hits, _ = search_companies(db, q, limit=COMPANY_HITS)
    out = [
        CompanyHit(
            cik=h.company.cik,
            legal_name=h.company.legal_name,
            ticker=h.company.ticker,
            exchange=h.company.exchange,
            match="former_name" if h.match_type == "former_name" else "name",
            matched_name=h.former_name,
            filings_url=company_filings_url(h.company.cik),
        )
        for h in hits
    ]
    if len(out) < COMPANY_HITS and db.get_bind().dialect.name == "postgresql":
        seen = {c.cik for c in out}
        vector = literal_column("company_documents.search_vector")
        tsq = func.websearch_to_tsquery(text("'english'::regconfig"), q)
        rows = db.execute(
            select(Company)
            .join(CompanyDocument, CompanyDocument.cik == Company.cik)
            .where(vector.op("@@")(tsq))
            .order_by(func.ts_rank_cd(vector, tsq).desc())
            .limit(COMPANY_HITS * 2)
        ).scalars()
        for c in rows:
            if c.cik not in seen and len(out) < COMPANY_HITS:
                out.append(
                    CompanyHit(
                        cik=c.cik,
                        legal_name=c.legal_name,
                        ticker=c.ticker,
                        exchange=c.exchange,
                        match="profile",
                        filings_url=company_filings_url(c.cik),
                    )
                )
    return out
