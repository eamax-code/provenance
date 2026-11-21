"""Keyless "Live from EDGAR" lists: stored data only, at most five rows, filing links only."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.db.models import Company, Filing, OfficerChange, utcnow
from app.services import live
from app.services import public as public_service

TODAY = date.today()


def _company(db, cik, name, ticker=None, sic=None):
    db.add(Company(cik=cik, legal_name=name, ticker=ticker, sic_code=sic, quality_status="ok",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow()))  # fmt: skip


def _filing(db, cik, accn, form, days_ago, items=None):
    db.add(
        Filing(
            id=uuid.uuid4(), cik=cik, accession_number=accn, form_type=form, items=items,
            first_detected_at=utcnow(), quality_status="ok",
            filing_date=TODAY - timedelta(days=days_ago),
            source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}-index.htm",
        )
    )  # fmt: skip


def test_public_ipos_and_events(client, db, fake_sec):
    public_service.reset_cache()
    _company(db, "0002130357", "Anthropic, PBC", "ANT")
    _company(db, "0000000001", "Quiet Co")  # no ticker yet
    _company(db, "0000000002", "Troubled Corp", "TRBL")
    _filing(db, "0002130357", "0002130357-26-000001", "S-1", 20)
    _filing(db, "0002130357", "0002130357-26-000002", "8-A12B", 4)
    _filing(db, "0002130357", "0002130357-26-000003", "424B4", 3)
    _filing(db, "0000000001", "0000000001-26-000001", "S-1", 2)
    _filing(db, "0000000002", "0000000002-26-000001", "8-K", 1, items="2.02,4.02,9.01")
    _filing(db, "0000000002", "0000000002-26-000002", "8-K", 2, items="2.02")
    _filing(db, "0000000002", "0000000002-26-000003", "10-Q", 1)  # not an event
    _filing(db, "0000000002", "0000000002-26-000009", "8-K", 40, items="1.03")  # too old
    db.add(
        OfficerChange(
            cik="0000000002", accession_number="0000000002-26-000004", seq=1,
            filing_date=TODAY - timedelta(days=1), person="Jane Roe",
            role="Executive Vice President and Chief Financial Officer",
            change_type="departure", source_url="https://www.sec.gov/Archives/x-index.htm",
            extractor_version="test",
        )
    )  # fmt: skip
    db.commit()

    calls = len(fake_sec.calls)
    r = client.get("/v1/public/ipos")
    assert r.status_code == 200 and r.headers["cache-control"].startswith("public")
    ipos = r.json()["data"]
    # newest milestone first: Quiet Co's S-1 (2 days ago), then Anthropic's 424B4 (3 days ago)
    assert [i["company_name"] for i in ipos] == ["Quiet Co", "Anthropic, PBC"]
    ant = ipos[1]
    assert ant["stage"] == "priced" and ant["form_type"] == "424B4" and ant["ticker"] == "ANT"
    assert ant["filing_url"].startswith("https://www.sec.gov/Archives/")
    assert ipos[0]["ticker"] is None and ipos[0]["stage"] == "filed"
    assert "not that shares trade" in r.json()["notes"][0]

    events = client.get("/v1/public/events").json()["data"]
    # newest first; on the same day the restatement outranks the officer change
    assert [(e["type"], e["short_label"]) for e in events] == [
        ("sec.restatement", "Restatement"),
        ("sec.officer_change", "CFO departs"),
        ("sec.results", "Results"),
    ]
    assert all(len(e["short_label"]) <= live.SHORT_MAX for e in events)
    assert all(e["filing_url"].startswith("https://www.sec.gov/") for e in events)
    assert len(fake_sec.calls) == calls  # never asks the SEC

    assert len(client.get("/v1/public/events?limit=1").json()["data"]) == 1
    assert client.get("/v1/public/events?limit=6").status_code == 422


def test_exchanges_and_form_10s_stay_off_the_strip(client, db):
    public_service.reset_cache()
    _company(db, "0001354457", "Nasdaq Stock Market LLC")
    _company(db, "0000000003", "Delisted Inc", "DLST")
    _company(db, "0000000004", "Some Fund LP")
    for n in range(live.EXCHANGE_FORM_25_MIN):
        _filing(db, "0001354457", f"0001354457-26-{n:06d}", "25-NSE", 1)
    _filing(db, "0000000003", "0001354457-26-000000", "25-NSE", 1)  # the same filing, issuer's row
    _filing(db, "0000000004", "0000000004-26-000001", "10-12G", 1)
    db.commit()
    events = client.get("/v1/public/events").json()["data"]
    assert [(e["company_name"], e["type"]) for e in events] == [("Delisted Inc", "sec.delisting")]
    assert client.get("/v1/public/ipos").json()["data"] == []  # a Form 10 is not an IPO


def test_deal_terms_reach_the_ipo_list_and_the_strip(client, db, auth):
    import json

    from app.db.models import IpoTerms

    public_service.reset_cache()
    _company(db, "0002130357", "Anthropic, PBC", "ANT")
    _filing(db, "0002130357", "0002130357-26-000001", "S-1", 20)
    _filing(db, "0002130357", "0002130357-26-000003", "424B4", 3)
    ev = "The initial public offering price per share is $83.00."
    db.add(IpoTerms(
        cik="0002130357", accession_number="0002130357-26-000003", form_type="424B4",
        filing_date=TODAY - timedelta(days=3), source_url="https://www.sec.gov/Archives/x.htm",
        extractor_version="ipo-terms-1",
        terms=json.dumps({"price_final": {"value": 83.0, "evidence": ev, "derived": False},
                          "currency": {"value": "USD", "evidence": ev, "derived": False}}),
    ))  # fmt: skip
    db.commit()
    row = client.get("/v1/public/ipos").json()["data"][0]
    assert row["price_final"] == 83.0 and row["currency"] == "USD" and row["price_low"] is None
    ipo = client.get("/v1/ipos?days=30", headers=auth).json()["data"][0]
    t = ipo["terms"]["price_final"]
    assert t["value"] == 83.0 and t["evidence"] == ev and t["form_type"] == "424B4"
    assert t["source_url"].startswith("https://www.sec.gov/")


def test_ipo_priced_is_the_first_424b4_after_registration_only(client, db):
    from app.services import filing_events, ipo_pipeline

    public_service.reset_cache()
    _company(db, "0002130357", "Anthropic, PBC", "ANT")
    _company(db, "0000000005", "Seasoned Co", "SEAS")
    _filing(db, "0002130357", "0002130357-26-000001", "S-1", 20)
    _filing(db, "0002130357", "0002130357-26-000003", "424B4", 3)
    _filing(db, "0000000005", "0000000005-24-000001", "10-K", 400)  # already reporting
    _filing(db, "0000000005", "0000000005-26-000001", "424B4", 2)  # a follow-on offering
    db.commit()
    assert ipo_pipeline.tag_all_priced(db) == 1
    assert ipo_pipeline.tag_all_priced(db) == 0  # idempotent
    assert filing_events.types_for("424B4", None, "sec.ipo_priced") == ["sec.ipo_priced"]
    assert filing_events.types_for("424B4", None, None) == []
    events = client.get("/v1/public/events").json()["data"]
    assert [(e["company_name"], e["short_label"]) for e in events] == [
        ("Anthropic, PBC", "IPO priced")
    ]
