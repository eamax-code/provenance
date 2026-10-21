import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from app.db.models import ListedInstrument, ListingEvent
from app.services.markets import canada
from app.services.markets.http import MarketHttp

FIX = Path(__file__).parents[1] / "fixtures/markets"
NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def _load(name):
    return json.loads((FIX / name).read_text())


def test_parse_tsx_combines_lists():
    recs = canada.parse_tsx(
        "tsx",
        _load("tsx_directory_tsx.json"),
        recent=_load("tsx_recent_tsx.json"),
        suspended=_load("tsx_suspended_tsx.json"),
    )
    by_sym = {r.symbol: r for r in recs}
    assert all(
        r.mic == "XTSE" and r.isin is None and r.listing_key == f"SYM:{r.symbol}" for r in recs
    )
    assert all(r.quality_status == "partial" and any("no ISIN" in n for n in r.notes) for r in recs)
    recent = _load("tsx_recent_tsx.json")["results"][0]
    assert (
        recent["symbol"] not in by_sym
        or by_sym[recent["symbol"]].first_trade_date
        == datetime.fromtimestamp(recent["date"], tz=UTC).date()
    )
    delisted = canada.parse_tsx("tsxv", {"results": []}, delisted=_load("tsx_delisted_tsxv.json"))
    assert delisted and all(
        d.status == "delisted" and d.mic == "XTSX" and d.termination_date for d in delisted
    )


def test_parse_cse_statuses_and_equity_filter():
    recs = canada.parse_cse(_load("cse_listed_companies.json"))
    statuses = {r.symbol: r.status for r in recs}
    assert (
        "listed" in statuses.values()
        and "suspended" in statuses.values()
        and "delisted" in statuses.values()
    )
    assert all(r.mic == "XCNQ" and r.first_trade_date is not None for r in recs)
    raw_types = {r["security_type"] for r in _load("cse_listed_companies.json")}
    if raw_types - {"Equity"}:
        assert len(recs) < len(_load("cse_listed_companies.json"))


def test_cse_ingest_end_to_end_and_delisting_event(db, settings, tmp_path):
    rows = _load("cse_listed_companies.json")

    def handler(request):
        return httpx.Response(200, json=rows)

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    s1 = canada.ingest_source(db, settings, http, "cse", now=NOW)
    assert s1["errors"] == [] and s1["inserted"] == s1["records"] > 0
    assert canada.ingest_source(db, settings, http, "cse", now=NOW)["updated"] == 0
    active = next(r for r in rows if r["status"] == "Active")
    active["status"] = "Delisted"
    s3 = canada.ingest_source(db, settings, http, "cse", now=NOW)
    assert s3["events"] == {"delisting": 1}
    ev = db.scalar(select(ListingEvent))
    assert (
        ev.symbol == active["symbol"]
        and ev.isin is None
        and ev.listing_key == f"SYM:{active['symbol']}"
    )
    assert (
        db.scalar(
            select(ListedInstrument).where(ListedInstrument.symbol == active["symbol"])
        ).status
        == "delisted"
    )


def test_tsx_ingest_handles_missing_extra_lists(db, settings, tmp_path):
    directory = _load("tsx_directory_tsx.json")

    def handler(request):
        url = str(request.url)
        if "/search/" in url:
            return httpx.Response(200, json=directory if "/tsx/" in url else {"results": []})
        return httpx.Response(503)

    http = MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path,
        sleep=lambda s: None,
    )
    s = canada.ingest_source(db, settings, http, "tsx", now=NOW)
    assert s["errors"] == [] and s["inserted"] == len(directory["results"])
    assert {r.mic for r in db.scalars(select(ListedInstrument))} == {"XTSE"}
