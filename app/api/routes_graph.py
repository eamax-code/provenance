"""A company's connections: insiders, their other companies, subsidiaries and 5% holders
(GH #24, ADR 0011)."""

from __future__ import annotations

import logging
import threading
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, settings_dep
from app.api.routes_companies import (
    _ERRORS,
    _parse_cik_param,
    _require_company,
    get_sec_client_factory,
)
from app.core.config import Settings
from app.core.errors import APIError
from app.db.models import Company, GraphSourceState, utcnow
from app.db.session import session_factory
from app.schemas.common import PageMeta
from app.schemas.graph import (
    FilingRef,
    GraphOut,
    HolderList,
    HolderOut,
    InsiderList,
    InsiderOut,
    InsiderTransactionList,
    InsiderTransactionOut,
    SubsidiaryList,
    SubsidiaryOut,
)
from app.services import beneficial_owners, company_graph, insiders, subsidiaries
from app.services.sec_client import SecClientError, filing_index_url

logger = logging.getLogger("app.api.graph")

router = APIRouter(prefix="/v1/companies", tags=["connections"])

STALE_AFTER = timedelta(days=7)
KINDS = ("subsidiaries", "holders", "insiders")
_inflight: set[str] = set()
_lock = threading.Lock()


def refresh_sources(db: Session, client, cik: str) -> dict:
    """Read a company's exhibit 21, structured 13D/G filings and Forms 3/4/5 newer than the
    loaded insider data sets. Each source records when it was checked."""
    out = {}
    for kind, fn in (
        ("subsidiaries", subsidiaries.refresh),
        ("holders", beneficial_owners.refresh),
        ("insiders", insiders.fill_recent),
    ):
        try:
            out[kind] = fn(db, client, cik)
        except SecClientError as exc:
            db.rollback()
            out[kind] = {"error": type(exc).__name__}
        if kind == "insiders":
            st = db.get(GraphSourceState, (cik, "insiders"))
            if st is None:
                st = GraphSourceState(cik=cik, kind="insiders", status="ok")
                db.add(st)
            st.status = "failed" if "error" in out[kind] else "ok"
            st.checked_at = utcnow()
            db.commit()
    return out


def _run_refresh(cik: str, client_factory) -> None:
    db = session_factory()()
    client = None
    try:
        client = client_factory()
        refresh_sources(db, client, cik)
    except Exception:  # noqa: BLE001
        logger.exception("graph refresh crashed", extra={"extra_fields": {"cik": cik}})
    finally:
        db.close()
        if client is not None:
            client.close()
        with _lock:
            _inflight.discard(cik)


def _maybe_refresh(
    request: Request, background: BackgroundTasks, db: Session, settings: Settings, cik: str
) -> bool:
    """Schedules a read of the company's sources when they are stale. Never for the demo key."""
    if getattr(request.state, "demo", False) or not settings.on_demand_ingestion_enabled:
        return False
    with _lock:
        if cik in _inflight:
            return True
    states = {
        s.kind: s.checked_at
        for s in db.scalars(select(GraphSourceState).where(GraphSourceState.cik == cik))
    }
    now = utcnow()
    if all(k in states and now - states[k] < STALE_AFTER for k in KINDS):
        return False
    with _lock:
        if cik in _inflight:
            return True
        _inflight.add(cik)
    background.add_task(_run_refresh, cik, get_sec_client_factory(request))
    return True


def _layers(include: str | None) -> tuple[str, ...]:
    if not include:
        return company_graph.LAYERS
    wanted = tuple(x.strip() for x in include.split(",") if x.strip())
    bad = [x for x in wanted if x not in company_graph.LAYERS]
    if bad:
        raise APIError(
            422,
            "invalid_parameter",
            f"include takes {', '.join(company_graph.LAYERS)}; got {', '.join(bad)}.",
        )
    return wanted


@router.get(
    "/{cik}/graph",
    response_model=GraphOut,
    responses=_ERRORS,
    summary="A company's connections as nodes and edges, each edge with its filing",
)
def graph(
    request: Request,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only filings made by this date"),
    include: str | None = Query(
        None, description="Comma-separated layers: insiders, interlocks, subsidiaries, holders"
    ),
    former: bool = Query(False, description="Include former insiders and holders below 5%"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    layers = _layers(include)
    refreshing = as_of is None and _maybe_refresh(request, background, db, settings, cik)
    out = company_graph.build(db, cik, as_of=as_of, layers=layers, former=former)
    return GraphOut(**out, refreshing=refreshing)


@router.get(
    "/{cik}/insiders",
    response_model=InsiderList,
    responses=_ERRORS,
    summary="Directors, officers and 10% owners from Forms 3, 4 and 5",
)
def list_insiders(
    request: Request,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only filings made by this date"),
    former: bool = Query(False, description="Include insiders who have not filed for two years"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    if as_of is None:
        _maybe_refresh(request, background, db, settings, cik)
    owners = insiders.roles(db, cik, as_of)
    if not former:
        owners = [o for o in owners if o["current"]]
    insiders.activity(db, cik, owners, as_of)
    other = insiders.other_roles(
        db, [o["owner_cik"] for o in owners if o["is_director"] or o["is_officer"]], cik, as_of
    )
    names = {
        c.cik: c
        for c in db.scalars(
            select(Company).where(
                Company.cik.in_(
                    sorted(
                        {o["owner_cik"] for o in owners}
                        | {r["issuer_cik"] for v in other.values() for r in v}
                    )  # fmt: skip
                )
            )
        )
    }
    data = []
    for o in owners:
        others = [
            {
                "cik": r["issuer_cik"],
                "name": names[r["issuer_cik"]].legal_name if r["issuer_cik"] in names else None,
                "role": r["role"],
                "current": r["current"],
                "last_filed": r["last_filed"],
            }
            for r in sorted(
                other.get(o["owner_cik"], []), key=lambda r: r["last_filed"], reverse=True
            )  # fmt: skip
            if former or r["current"]
        ]
        data.append(
            InsiderOut(
                **{k: o[k] for k in InsiderOut.model_fields if k in o},
                latest_filing=FilingRef(
                    form_type=o["last_form"],
                    accession_number=o["last_accession"],
                    filing_date=o["last_filed"],
                    source_url=filing_index_url(cik, o["last_accession"]),
                ),
                company_cik=o["owner_cik"] if o["owner_cik"] in names else None,
                other_companies=others,
            )
        )
    return InsiderList(data=data, through=insiders.dataset_coverage(db), as_of=as_of)


@router.get(
    "/{cik}/insider-transactions",
    response_model=InsiderTransactionList,
    responses=_ERRORS,
    summary="Insider purchases, sales, grants and exercises from Forms 3, 4 and 5",
)
def list_insider_transactions(
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only filings made by this date"),
    since: date | None = Query(None, description="Transactions on or after this date"),
    code: str | None = Query(
        None, max_length=40, description="Comma-separated transaction codes, e.g. P,S"
    ),
    owner_cik: str | None = Query(None, max_length=13),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    codes = {c.strip().upper() for c in code.split(",") if c.strip()} if code else None
    if codes and not codes <= set(insiders.CODE_LABELS):
        raise APIError(422, "invalid_parameter", "Unknown transaction code.")
    if owner_cik:
        owner_cik = _parse_cik_param(owner_cik)
    rows, more = insiders.transactions(
        db, cik, as_of=as_of, since=since, codes=codes, owner_cik=owner_cik, limit=limit,
        offset=offset,
    )  # fmt: skip
    data = []
    for t, f in rows:
        value = float(t.shares * t.price) if t.shares is not None and t.price is not None else None
        data.append(
            InsiderTransactionOut(
                accession_number=t.accession_number,
                filing_date=f.filing_date,
                form_type=f.form_type,
                owner_cik=f.owner_cik,
                owner_name=insiders.display_name(f.owner_name),
                role=insiders.role_label(insiders._flags(f)),
                security_title=t.security_title,
                is_derivative=t.is_derivative,
                trans_date=t.trans_date,
                trans_code=t.trans_code,
                trans_code_label=insiders.CODE_LABELS.get(t.trans_code or ""),
                acquired_disposed=t.acquired_disposed,
                shares=float(t.shares) if t.shares is not None else None,
                price=float(t.price) if t.price is not None else None,
                value=value,
                shares_after=float(t.shares_after) if t.shares_after is not None else None,
                direct_indirect=t.direct_indirect,
                plan_10b5_1=f.plan_10b5_1,
                source_url=filing_index_url(cik, t.accession_number),
            )
        )
    return InsiderTransactionList(
        data=data,
        meta=PageMeta(
            limit=limit, offset=offset, has_more=more, next_offset=offset + limit if more else None
        ),  # fmt: skip
    )


@router.get(
    "/{cik}/subsidiaries",
    response_model=SubsidiaryList,
    responses=_ERRORS,
    summary="Subsidiaries from the latest exhibit 21, with those new since the year before",
)
def list_subsidiaries(
    request: Request,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only filings made by this date"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    refreshing = as_of is None and _maybe_refresh(request, background, db, settings, cik)
    st = db.get(GraphSourceState, (cik, "subsidiaries"))
    lst = subsidiaries.latest(db, cik, as_of)
    if lst is None:
        return SubsidiaryList(data=[], filing=None, exhibit=None, previous=None, added=[],
                              removed=[], checked_at=st and st.checked_at,
                              refreshing=refreshing)  # fmt: skip
    added = {subsidiaries._norm(n) for n in lst["added"]}
    matched = company_graph._companies_named(db, [r.name for r in lst["rows"]])
    return SubsidiaryList(
        data=[
            SubsidiaryOut(
                name=r.name,
                jurisdiction=r.jurisdiction,
                jurisdiction_group=subsidiaries.jurisdiction_group(r.jurisdiction),
                new_this_year=lst["previous"] is not None and subsidiaries._norm(r.name) in added,
                company_cik=matched[r.name].cik if r.name in matched else None,
            )
            for r in lst["rows"]
        ],
        filing=FilingRef(
            form_type=lst["form_type"],
            accession_number=lst["accession_number"],
            filing_date=lst["filing_date"],
            source_url=lst["source_url"],
        ),
        exhibit=lst["exhibit"],
        previous=lst["previous"],
        added=lst["added"],
        removed=lst["removed"],
        checked_at=st and st.checked_at,
        refreshing=refreshing,
    )


@router.get(
    "/{cik}/holders",
    response_model=HolderList,
    responses=_ERRORS,
    summary="Holders of more than 5% from Schedules 13D and 13G",
)
def list_holders(
    request: Request,
    background: BackgroundTasks,
    cik: str = Path(max_length=13),
    as_of: date | None = Query(None, description="Use only filings made by this date"),
    below: bool = Query(False, description="Include holders whose latest stake is below 5%"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    cik = _parse_cik_param(cik)
    _require_company(db, cik)
    refreshing = as_of is None and _maybe_refresh(request, background, db, settings, cik)
    hs = beneficial_owners.holders(db, cik, as_of, below=below)
    known = {
        c.cik
        for c in db.scalars(
            select(Company).where(Company.cik.in_([h["cik"] for h in hs if h["cik"]]))
        )
    }
    return HolderList(
        data=[
            HolderOut(
                **{k: h[k] for k in HolderOut.model_fields if k in h},
                filing=FilingRef(
                    form_type=h["form_type"],
                    accession_number=h["accession_number"],
                    filing_date=h["filing_date"],
                    source_url=h["source_url"],
                ),
                company_cik=h["cik"] if h["cik"] in known else None,
            )
            for h in hs
        ],
        as_of=as_of,
        note=beneficial_owners.__doc__.split("\n\n")[1].replace("\n", " "),
        refreshing=refreshing,
    )
