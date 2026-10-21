from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import Issuer, ListedInstrument, ListingEvent
from app.services.markets import ingest
from app.services.markets.records import ListingRecord, is_valid_isin

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def _markets(db):
    ingest.ensure_market(
        db,
        "XPAR",
        "Euronext Paris",
        "FR",
        "europe",
        "esma_firds",
        "https://registers.esma.europa.eu/",
    )
    ingest.ensure_market(
        db, "XTSE", "Toronto Stock Exchange", "CA", "canada", "tsx", "https://www.tsx.com/"
    )
    db.commit()


def _rec(**kw):
    base = dict(
        isin="FR0000120271",
        mic="XPAR",
        issuer_name="TotalEnergies SE",
        source="esma_firds",
        source_url="https://registers.esma.europa.eu/x",
        issuer_lei="529900S21EQ1BO4ESM68",
        short_name="TTE",
        cfi_code="ESVUFB",
        currency="EUR",
        first_trade_date=date(1990, 1, 2),
    )
    base.update(kw)
    return ListingRecord(**base)


def test_isin_validation():
    assert (
        is_valid_isin("US0378331005")
        and is_valid_isin("FR0000120271")
        and is_valid_isin("CA0679011084")
    )
    assert (
        not is_valid_isin("US0378331006")
        and not is_valid_isin("us0378331005")
        and not is_valid_isin("FR00001202")
        and not is_valid_isin("")
    )


def test_insert_is_idempotent_and_backfill_raises_no_event(db):
    _markets(db)
    r1 = ingest.ingest_records(db, [_rec()], "esma_firds", now=NOW)
    assert (r1.inserted, r1.updated, r1.unchanged) == (1, 0, 0) and r1.events == {}
    r2 = ingest.ingest_records(db, [_rec()], "esma_firds", now=NOW + timedelta(days=1))
    assert (r2.inserted, r2.updated, r2.unchanged) == (0, 0, 1)
    row = db.scalar(select(ListedInstrument))
    assert (
        row.first_detected_at == NOW
        and row.last_seen_at == NOW + timedelta(days=1)
        and row.status == "listed"
    )
    issuer = db.scalar(select(Issuer))
    assert issuer.lei == "529900S21EQ1BO4ESM68" and issuer.legal_name == "TotalEnergies SE"


def test_recent_first_trade_date_raises_new_listing_with_first_listing_flag(db):
    _markets(db)
    res = ingest.ingest_records(
        db,
        [
            _rec(
                isin="FR001400AJ45",
                issuer_name="Exosens",
                issuer_lei="969500ABCDEFGHIJ1234",
                first_trade_date=NOW.date() - timedelta(days=3),
            )
        ],
        "esma_firds",
        now=NOW,
    )
    assert res.events == {"new_listing": 1}
    ev = db.scalar(select(ListingEvent))
    assert ev.event_type == "new_listing" and ev.event_date == NOW.date() - timedelta(days=3)
    assert '"first_listing_for_issuer_in_our_data": true' in ev.details
    # second line for the same issuer is not a "first listing"
    ingest.ingest_records(
        db,
        [
            _rec(
                isin="FR001400AJ52",
                mic="XPAR",
                issuer_name="Exosens",
                issuer_lei="969500ABCDEFGHIJ1234",
                first_trade_date=NOW.date(),
            )
        ],
        "esma_firds",
        now=NOW,
    )
    second = db.scalars(select(ListingEvent).order_by(ListingEvent.detected_at)).all()[-1]
    assert '"first_listing_for_issuer_in_our_data": false' in second.details
    # re-ingesting the same delta never duplicates the event
    ingest.ingest_records(
        db,
        [
            _rec(
                isin="FR001400AJ45",
                issuer_name="Exosens",
                issuer_lei="969500ABCDEFGHIJ1234",
                first_trade_date=NOW.date() - timedelta(days=3),
            )
        ],
        "esma_firds",
        now=NOW + timedelta(hours=1),
    )
    assert db.scalar(select(func.count(ListingEvent.id))) == 2


def test_termination_date_raises_delisting_once(db):
    _markets(db)
    ingest.ingest_records(db, [_rec()], "esma_firds", now=NOW)
    res = ingest.ingest_records(
        db, [_rec(termination_date=NOW.date() - timedelta(days=1))], "esma_firds", now=NOW
    )
    assert res.updated == 1 and res.events == {"delisting": 1}
    row = db.scalar(select(ListedInstrument))
    assert row.status == "delisted"
    again = ingest.ingest_records(
        db,
        [_rec(termination_date=NOW.date() - timedelta(days=1))],
        "esma_firds",
        now=NOW + timedelta(days=1),
    )
    assert again.unchanged == 1 and db.scalar(select(func.count(ListingEvent.id))) == 1
    # a future termination date keeps the instrument listed until the date passes
    ingest.ingest_records(
        db,
        [
            _rec(
                isin="FR0000131104",
                issuer_name="BNP Paribas",
                termination_date=NOW.date() + timedelta(days=10),
            )
        ],
        "esma_firds",
        now=NOW,
    )
    assert (
        db.scalar(select(ListedInstrument).where(ListedInstrument.isin == "FR0000131104")).status
        == "listed"
    )


def test_old_delisting_seen_first_time_is_backfill(db):
    _markets(db)
    res = ingest.ingest_records(
        db, [_rec(termination_date=date(2015, 3, 3))], "esma_firds", now=NOW
    )
    assert res.inserted == 1 and res.events == {}
    assert db.scalar(select(ListedInstrument)).status == "delisted"


def test_name_change_and_suspension_events(db):
    _markets(db)
    ingest.ingest_records(db, [_rec()], "esma_firds", now=NOW)
    res = ingest.ingest_records(
        db,
        [_rec(issuer_name="TotalEnergies SE (renamed)", short_name="TTE2")],
        "esma_firds",
        now=NOW,
    )
    assert res.events == {"modified": 1}
    ev = db.scalar(select(ListingEvent).where(ListingEvent.event_type == "modified"))
    assert '"issuer_name"' in ev.details and '"short_name"' in ev.details
    res = ingest.ingest_records(
        db,
        [_rec(issuer_name="TotalEnergies SE (renamed)", short_name="TTE2", status="suspended")],
        "esma_firds",
        now=NOW,
    )
    assert res.events == {"suspended": 1}
    res = ingest.ingest_records(
        db,
        [_rec(issuer_name="TotalEnergies SE (renamed)", short_name="TTE2", status="listed")],
        "esma_firds",
        now=NOW,
    )
    assert res.events == {"reinstated": 1}


def test_explicit_ipo_from_source(db):
    _markets(db)
    res = ingest.ingest_records(
        db,
        [
            _rec(
                isin="CA0679011084",
                mic="XTSE",
                issuer_name="Maple Co",
                issuer_lei=None,
                first_trade_date=NOW.date(),
                explicit_event="ipo",
                source="tsx",
            )
        ],
        "tsx",
        now=NOW,
    )
    assert res.events == {"ipo": 1, "new_listing": 1}


def test_invalid_isin_and_unknown_mic_are_skipped(db):
    _markets(db)
    res = ingest.ingest_records(db, [_rec(isin="BAD"), _rec(mic="XXXX")], "esma_firds", now=NOW)
    assert res.skipped == 2 and res.inserted == 0


def test_missing_issuer_name_is_partial(db):
    _markets(db)
    ingest.ingest_records(
        db, [_rec(issuer_name="", issuer_lei=None, short_name="MYST")], "esma_firds", now=NOW
    )
    row = db.scalar(select(ListedInstrument))
    assert row.issuer_name == "MYST" and row.quality_status == "partial"
