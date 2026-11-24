"""F-03: insider activity found by rules in Forms 4; backfill never notifies."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Company, InsiderActivity, InsiderFiling, InsiderTransaction, utcnow
from app.services import events, insider_activity
from app.services import public as public_service

CIK = "0000320193"
D0 = date.today() - timedelta(days=20)


def _company(db):
    db.add(Company(cik=CIK, legal_name="Apple Inc.", ticker="AAPL", quality_status="ok",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow()))  # fmt: skip


def _trade(db, n, owner, day, code, shares, price, officer=True, plan=None, director=False,
           form="4", filed=None):  # fmt: skip
    accn = f"0001-26-{n:06d}"
    db.add(InsiderFiling(
        accession_number=accn, issuer_cik=CIK, owner_cik=f"{owner:010d}",
        owner_name=f"OWNER {owner}", is_officer=officer, is_director=director,
        officer_title="CFO" if officer else None, form_type=form, filing_date=filed or day,
        period_of_report=day, plan_10b5_1=plan, source="filing",
    ))  # fmt: skip
    db.add(InsiderTransaction(
        accession_number=accn, issuer_cik=CIK, row_kind="transaction", is_derivative=False,
        row_key=f"{n}", trans_date=day, trans_code=code, shares=Decimal(shares),
        price=Decimal(price),
    ))  # fmt: skip
    return accn


def test_rules_and_backfill(db, client, auth, settings):
    settings.events_settle_seconds = 0
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)  # owner 1, long ago (sets data coverage)
    _trade(db, 2, 1, D0, "P", 1000, 50)  # owner 1 again after more than two years: first buy
    _trade(db, 3, 2, D0 + timedelta(days=3), "P", 500, 50)
    third = _trade(db, 4, 3, D0 + timedelta(days=9), "P", 500, 50)  # third insider: cluster
    _trade(db, 5, 4, D0 + timedelta(days=10), "S", 30000, 40, plan=False)  # $1.2M, no plan
    _trade(db, 6, 5, D0 + timedelta(days=10), "S", 30000, 40, plan=True)  # under a plan
    _trade(db, 7, 6, D0 + timedelta(days=10), "S", 10000, 40, plan=False)  # $0.4M: too small
    db.commit()
    found = insider_activity.detect(db, CIK, start)
    kinds = [(a["type"], a["trade"].accession) for a in found]
    assert (insider_activity.CLUSTER, third) in kinds
    assert [a for a in found if a["type"] == insider_activity.FIRST_BUY][0]["detail"][
        "previous_purchase"] == start.isoformat()  # fmt: skip
    sales = [a for a in found if a["type"] == insider_activity.LARGE_SALE]
    assert len(sales) == 1 and sales[0]["detail"]["value_usd"] == 1_200_000
    # backfill: stored but never on the feed
    rows = insider_activity.store(db, CIK, None, start)
    db.commit()
    assert rows and {r.stream_status for r in rows} == {"skipped"}
    assert insider_activity.store(db, CIK, None, start) == []  # idempotent
    # a new Form 4 found later is published
    new = _trade(db, 8, 7, D0 + timedelta(days=12), "S", 50000, 40, plan=False)
    db.commit()
    fresh = insider_activity.store(db, CIK, {new}, start)
    db.commit()
    assert [r.stream_status for r in fresh] == ["pending"]
    events.publish_pending(db)
    feed = client.get("/v1/events?types=insider&since=" + (utcnow() - timedelta(hours=1))
                      .isoformat().replace("+00:00", "Z"), headers=auth).json()["data"]  # fmt: skip
    assert [e["type"] for e in feed] == [insider_activity.LARGE_SALE]
    assert "not under a 10b5-1 plan" in feed[0]["data"]["label"]
    typed = client.get("/v1/events?event_type=sec.insider_large_sale&since="
                       + (utcnow() - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                       headers=auth)  # fmt: skip
    assert typed.status_code == 200 and len(typed.json()["data"]) == 1
    public_service.reset_cache()
    strip = client.get("/v1/public/insider-activity").json()["data"]
    assert strip and all(len(r["short_label"]) <= 24 for r in strip)
    assert "signal" not in str(strip).lower()
    assert db.scalar(select(InsiderActivity).limit(1)) is not None


def test_a_trade_cancelled_or_restated_by_a_4a_counts_as_amended(db):
    """Q-03d: a purchase a 4/A cancels ("No such sale has occurred": 0 shares) is no cluster
    buyer, and a sale a 4/A restates below $1 million is no large sale; a paired 4/A never
    counts on its own."""
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)
    _trade(db, 2, 1, D0, "P", 1000, 50)
    _trade(db, 3, 2, D0 + timedelta(days=3), "P", 500, 50)
    _trade(db, 4, 3, D0 + timedelta(days=9), "P", 500, 50)  # would be the third buyer
    _trade(db, 5, 3, D0 + timedelta(days=9), "P", 0, 0, form="4/A",
           filed=D0 + timedelta(days=10))  # fmt: skip
    _trade(db, 6, 4, D0 + timedelta(days=10), "S", 30000, 40, plan=False)  # $1.2M as filed
    _trade(db, 7, 4, D0 + timedelta(days=10), "S", 10000, 40, plan=False, form="4/A",
           filed=D0 + timedelta(days=12))  # restated: $0.4M  # fmt: skip
    db.commit()
    found = insider_activity.detect(db, CIK, start)
    kinds = {a["type"] for a in found}
    assert insider_activity.CLUSTER not in kinds
    assert insider_activity.LARGE_SALE not in kinds
    buys = [a for a in found if a["type"] == insider_activity.FIRST_BUY]
    # owners 1 and 2; not owner 3 (cancelled), and the 4/A is no buy of its own
    assert [a["trade"].accession for a in buys] == ["0001-26-000002", "0001-26-000003"]


def test_owners_a_4a_adds_bought_on_the_trade_date(db):
    """A 4/A that repeats the trade and adds reporting owners (a fund's general partners): each
    added owner's purchase is on the trade's own date, not their next filing."""
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)
    orig = _trade(db, 2, 7, D0, "P", 1000, 10)
    amend = _trade(db, 3, 7, D0, "P", 1000, 10, form="4/A", filed=D0 + timedelta(days=5))
    db.add(InsiderFiling(accession_number=amend, issuer_cik=CIK, owner_cik=f"{8:010d}",
                         owner_name="OWNER 8", is_officer=False, is_director=True,
                         form_type="4/A", filing_date=D0 + timedelta(days=5),
                         period_of_report=D0, source="filing"))  # fmt: skip
    db.commit()
    buys = [a for a in insider_activity.detect(db, CIK, start)
            if a["type"] == insider_activity.FIRST_BUY]  # fmt: skip
    got = {a["owners"][0]["owner_cik"]: (a["trade"].accession, a["trade"].trans_date) for a in buys}
    assert got == {f"{7:010d}": (orig, D0), f"{8:010d}": (orig, D0)}
