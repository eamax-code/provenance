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
