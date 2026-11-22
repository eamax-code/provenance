from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_reader, strict_query
from app.core.errors import APIError
from app.db.models import Issuer, ListedInstrument, ListingEvent, Market
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.markets import (
    InstrumentDetail,
    InstrumentList,
    InstrumentOut,
    IssuerDetail,
    IssuerOut,
    ListingEventList,
    ListingEventOut,
    MarketList,
    MarketOut,
)
from app.services import identity
from app.services.markets.records import EVENT_TYPES, STATUSES, is_valid_isin

router = APIRouter(prefix="/v1/markets", tags=["markets"])
_ERRORS = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}

NOTES = [
    "Listing data comes from official regulator registers and exchange lists (see source on "
    "each row); coverage is limited to the venues this deployment ingests.",
    "new_listing means an instrument first traded on a venue recently; it is not an IPO "
    "determination. ipo events exist only where the source states an IPO.",
    "Independent service, not affiliated with ESMA, the FCA, the CSA, TMX or any exchange.",
]


@router.get(
    "/",
    response_model=MarketList,
    responses=_ERRORS,
    summary="Venues covered in Canada, the UK and the EU, with counts",
)
def markets(db: Session = Depends(db_session), _key=Depends(require_reader)):
    rows = db.scalars(select(Market).order_by(Market.region, Market.country, Market.mic)).all()
    counts = {
        (mic, status): int(n)
        for mic, status, n in db.execute(
            select(
                ListedInstrument.mic, ListedInstrument.status, func.count(ListedInstrument.id)
            ).group_by(ListedInstrument.mic, ListedInstrument.status)
        ).all()
    }
    seen = {
        mic: ts
        for mic, ts in db.execute(
            select(ListedInstrument.mic, func.max(ListedInstrument.last_seen_at)).group_by(
                ListedInstrument.mic
            )
        ).all()
    }
    out = []
    for m in rows:
        o = MarketOut.model_validate(m)
        o.instruments_listed = counts.get((m.mic, "listed"), 0)
        o.instruments_delisted = counts.get((m.mic, "delisted"), 0)
        o.last_seen_at = seen.get(m.mic)
        out.append(o)
    return MarketList(data=out, notes=NOTES)


@router.get(
    "/instruments",
    response_model=InstrumentList,
    responses=_ERRORS,
    summary="Listed instruments by venue, country, region, status or name",
)
def instruments(
    mic: str | None = Query(None, min_length=4, max_length=4),
    country: str | None = Query(None, min_length=2, max_length=2),
    region: str | None = Query(None, pattern="^(canada|europe|uk)$"),
    status: str | None = Query(None, pattern="^(listed|delisted|suspended)$"),
    q: str | None = Query(
        None, min_length=2, max_length=100, description="Issuer name, symbol, ISIN or LEI"
    ),
    first_trade_since: date | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    stmt = select(ListedInstrument).join(Market, Market.mic == ListedInstrument.mic)
    if mic:
        stmt = stmt.where(ListedInstrument.mic == mic.upper())
    if country:
        stmt = stmt.where(Market.country == country.upper())
    if region:
        stmt = stmt.where(Market.region == region)
    if status:
        stmt = stmt.where(ListedInstrument.status == status)
    if first_trade_since:
        stmt = stmt.where(ListedInstrument.first_trade_date >= first_trade_since)
    if q:
        like = "%" + q.lower().replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(
            or_(
                func.lower(ListedInstrument.issuer_name).like(like, escape="\\"),
                func.upper(ListedInstrument.symbol) == q.upper(),
                ListedInstrument.isin == q.upper(),
                ListedInstrument.issuer_lei == q.upper(),
            )
        )
    stmt = (
        stmt.order_by(
            ListedInstrument.first_trade_date.desc().nulls_last(),
            ListedInstrument.listing_key,
            ListedInstrument.mic,
        )
        .offset(offset)
        .limit(limit + 1)
    )
    rows = db.scalars(stmt).all()
    has_more = len(rows) > limit
    return InstrumentList(
        data=[InstrumentOut.model_validate(r) for r in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )


@router.get(
    "/instruments/{isin}",
    response_model=InstrumentDetail,
    responses=_ERRORS,
    summary="One instrument's listings across venues and its issuer",
)
def instrument(
    isin: str = Path(min_length=12, max_length=12),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    isin = isin.upper()
    if not is_valid_isin(isin):
        raise APIError(422, "invalid_parameter", "isin must be a valid ISO 6166 identifier.")
    rows = db.scalars(
        select(ListedInstrument).where(ListedInstrument.isin == isin).order_by(ListedInstrument.mic)
    ).all()
    if not rows:
        raise APIError(404, "instrument_not_found", "No listing with this ISIN is available.")
    issuer = None
    lei = next((r.issuer_lei for r in rows if r.issuer_lei), None)
    if lei:
        issuer = db.scalar(select(Issuer).where(Issuer.lei == lei))
    if issuer is None:
        issuer = db.scalar(
            select(Issuer).where(Issuer.lei.is_(None), Issuer.legal_name == rows[0].issuer_name)
        )
    return InstrumentDetail(
        isin=isin,
        listings=[InstrumentOut.model_validate(r) for r in rows],
        issuer=IssuerOut.model_validate(issuer) if issuer else None,
        notes=NOTES,
    )


@router.get(
    "/events",
    response_model=ListingEventList,
    responses=_ERRORS,
    summary="New listings, delistings, suspensions and changes",
    dependencies=[Depends(strict_query)],
)
def events(
    event_type: str | None = Query(
        None, description="Comma-separated event types: " + ", ".join(EVENT_TYPES)
    ),
    types: str | None = Query(
        None, deprecated=True, description="Deprecated alias of `event_type`; removed at 1.0."
    ),
    type: str | None = Query(
        None, deprecated=True, description="Deprecated alias of `event_type`; removed at 1.0."
    ),
    mic: str | None = Query(None, min_length=4, max_length=4),
    region: str | None = Query(None, pattern="^(canada|europe|uk)$"),
    isin: str | None = Query(None, min_length=12, max_length=12, description="One instrument"),
    since: date | None = Query(None, description="Events dated on or after this date"),
    until: date | None = Query(None, description="Events dated on or before this date"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    given = (event_type, types, type)
    wanted = [t.strip() for v in given if v for t in v.split(",") if t.strip()]
    bad = sorted(set(wanted) - set(EVENT_TYPES))
    if bad:
        raise APIError(
            422,
            "invalid_parameter",
            f"Unknown event type: {', '.join(bad)}. event_type must be among: "
            f"{', '.join(EVENT_TYPES)}.",
        )
    stmt = select(ListingEvent).join(Market, Market.mic == ListingEvent.mic)
    if wanted:
        stmt = stmt.where(ListingEvent.event_type.in_(sorted(set(wanted))))
    if mic:
        stmt = stmt.where(ListingEvent.mic == mic.upper())
    if region:
        stmt = stmt.where(Market.region == region)
    if isin:
        stmt = stmt.where(ListingEvent.isin == isin.upper())
    if since:
        stmt = stmt.where(ListingEvent.event_date >= since)
    if until:
        stmt = stmt.where(ListingEvent.event_date <= until)
    stmt = (
        # the event's own date first; when we saw it only breaks ties, and is never returned
        stmt.order_by(
            ListingEvent.event_date.desc().nulls_last(),
            ListingEvent.detected_at.desc(),
            ListingEvent.listing_key,
        )
        .offset(offset)
        .limit(limit + 1)
    )
    rows = db.scalars(stmt).all()
    has_more = len(rows) > limit
    return ListingEventList(
        data=[ListingEventOut.model_validate(r) for r in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
        notes=NOTES,
    )


@router.get(
    "/issuers/{lei}",
    response_model=IssuerDetail,
    responses=_ERRORS,
    summary="An issuer by LEI, with its listed instruments",
)
def issuer(
    lei: str = Path(min_length=20, max_length=20),
    db: Session = Depends(db_session),
    _key=Depends(require_reader),
):
    row = db.scalar(select(Issuer).where(Issuer.lei == lei.upper()))
    if row is None:
        raise APIError(404, "issuer_not_found", "No issuer with this LEI is available.")
    listings = db.scalars(
        select(ListedInstrument)
        .where(ListedInstrument.issuer_lei == row.lei)
        .order_by(ListedInstrument.mic)
    ).all()
    return IssuerDetail(
        issuer=IssuerOut.model_validate(row),
        listings=[InstrumentOut.model_validate(r) for r in listings],
        sec_cik=identity.cik_for_lei(db, row.lei),
    )


_ = STATUSES  # documented vocabulary; referenced for completeness
