"""F-03: insider activity found by rules in Forms 4; backfill never notifies."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

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


def test_stored_events_are_corrected_never_deleted(db, client, auth, settings):
    """F-03c: events stored under the rules before 049fef3 are corrected as such: one a 4/A
    counted twice is retracted with its reason and leaves the feed and the public strip; one
    whose 4/A changed its figures is updated with what it said before; one found only now is
    added as backfill. Nothing is deleted."""
    import json

    settings.events_settle_seconds = 0
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)
    sale = _trade(db, 2, 4, D0, "S", 30000, 40, plan=False)  # $1.2M
    twin = _trade(db, 3, 4, D0, "S", 30000, 40, plan=False, form="4/A",
                  filed=D0 + timedelta(days=2))  # the same sale again  # fmt: skip
    other = _trade(db, 4, 5, D0, "S", 30000, 40, plan=False)  # $1.2M as first filed
    _trade(db, 5, 5, D0, "S", 30000, 50, plan=False, form="4/A",
           filed=D0 + timedelta(days=3))  # restated: $1.5M  # fmt: skip
    small = _trade(db, 6, 6, D0, "S", 20000, 40, plan=False)  # $0.8M as first filed
    _trade(db, 7, 6, D0, "S", 30000, 40, plan=False, form="4/A",
           filed=D0 + timedelta(days=3))  # restated: $1.2M, a large sale now  # fmt: skip
    db.commit()
    now = utcnow()
    for a in insider_activity.detect(db, CIK, start, amended=False):  # as stored before
        t = a["trade"]
        db.add(InsiderActivity(cik=CIK, activity_type=a["type"], activity_date=t.trans_date,
                               filing_date=t.filing_date, accession_number=t.accession,
                               owners=json.dumps(a["owners"]), detail=json.dumps(a["detail"]),
                               source_url="https://www.sec.gov/Archives/x",
                               stream_status="published", stream_at=now))  # fmt: skip
    db.commit()
    before = db.scalar(select(func.count()).select_from(InsiderActivity))
    acts = insider_activity.reconcile(db, CIK, start, write=True, now=now)
    db.commit()
    got = {(a["action"], a["key"][1]) for a in acts if a["key"][0] == insider_activity.LARGE_SALE}
    # the 4/As counted as sales of their own are retracted too (#5, #7)
    assert got == {("retract", twin), ("retract", "0001-26-000005"),
                   ("retract", "0001-26-000007"), ("update", other), ("add", small)}  # fmt: skip
    assert db.scalar(select(func.count()).select_from(InsiderActivity)) == before + 1
    rows = {r.accession_number: r for r in db.scalars(select(InsiderActivity).where(
        InsiderActivity.activity_type == insider_activity.LARGE_SALE))}  # fmt: skip
    gone = insider_activity.as_dict(rows[twin])
    assert gone["status"] == "retracted" and "counted twice" in gone["retraction_reason"]
    fixed = insider_activity.as_dict(rows[other])
    assert fixed["detail"]["value_usd"] == 1_500_000
    assert fixed["previous_values"]["detail"]["value_usd"] == 1_200_000
    assert rows[small].stream_status == "skipped" and rows[sale].status == "active"
    since = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    feed = client.get(f"/v1/events?types=insider&since={since}", headers=auth).json()["data"]
    assert twin not in {e["data"]["accession_number"] for e in feed}
    public_service.reset_cache()
    strip = client.get("/v1/public/insider-activity?limit=5").json()["data"]
    assert twin not in {r["accession_number"] for r in strip}
    frm = (D0 - timedelta(days=30)).isoformat()
    tl = client.get(f"/v1/companies/{CIK}/timeline?types=insider&from={frm}", headers=auth).json()
    accs = {i.get("accession_number") for i in tl["data"]}
    assert other in accs and twin not in accs
    assert insider_activity.reconcile(db, CIK, start) == []  # done once


def test_chat_leaves_out_retracted_events(db):
    """F-03c: chat's insider answer cites active events only."""
    import json

    from app.services import chat_intents
    from app.services.intel import Brief

    _company(db)
    for n, day, status in ((1, D0, "active"), (2, D0 + timedelta(days=5), "retracted")):
        db.add(InsiderActivity(cik=CIK, activity_type=insider_activity.LARGE_SALE,
                               activity_date=day, filing_date=day, accession_number=f"x-{n}",
                               owners=json.dumps([]), detail=json.dumps({"value_usd": 2e6}),
                               source_url=f"https://www.sec.gov/Archives/{n}",
                               status=status))  # fmt: skip
    db.commit()
    company = db.scalar(select(Company).where(Company.cik == CIK))
    text = chat_intents.insiders(db, Brief(company=company, as_of=None), None, "insider activity")
    assert str(D0) in text and str(D0 + timedelta(days=5)) not in text


def test_joint_filers_are_one_buyer(db):
    """F-03b: the reporting owners of one Form 4 (a fund, its general partner, its manager) are
    one buyer, and so are entities that ever file together; a cluster needs three buyers filing
    apart (CIK 1037390: one fund group of seven entities made every purchase a cluster)."""
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)
    joint = _trade(db, 2, 11, D0, "P", 100, 10)  # owners 11, 12 and 13 on one Form 4
    for owner in (12, 13):
        db.add(InsiderFiling(accession_number=joint, issuer_cik=CIK, owner_cik=f"{owner:010d}",
                             owner_name=f"OWNER {owner}", is_officer=False, is_director=False,
                             form_type="4", filing_date=D0, period_of_report=D0,
                             source="filing"))  # fmt: skip
    _trade(db, 3, 12, D0 + timedelta(days=2), "P", 100, 10)  # the same group, on its own
    db.commit()
    kinds = [a["type"] for a in insider_activity.detect(db, CIK, start)]
    assert insider_activity.CLUSTER not in kinds
    assert insider_activity.CLUSTER in [  # as counted before F-03b
        a["type"] for a in insider_activity.detect(db, CIK, start, joint_as_one=False)
    ]
    _trade(db, 4, 21, D0 + timedelta(days=3), "P", 100, 10)  # two more buyers, filing apart
    _trade(db, 5, 22, D0 + timedelta(days=4), "P", 100, 10)
    db.commit()
    cl = [a for a in insider_activity.detect(db, CIK, start)
          if a["type"] == insider_activity.CLUSTER]  # fmt: skip
    assert len(cl) == 1 and cl[0]["detail"]["insiders"] == 3  # the group, 21 and 22


def test_old_clusters_newly_found_wait_for_f03d(db, monkeypatch):
    """F-03b hold (lifted with F-03d): while it is on, for a company already stored, a cluster the
    joint-filer rule newly finds in old filings is not added by the tracker's store(); one formed
    by a new filing is. With it off, the old one is stored as backfill."""
    monkeypatch.setattr(insider_activity, "HOLD_OLD_CLUSTERS", True)
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)
    _trade(db, 2, 2, D0, "P", 100, 10)
    _trade(db, 3, 3, D0 + timedelta(days=1), "P", 100, 10)
    third = _trade(db, 4, 4, D0 + timedelta(days=2), "P", 100, 10)
    db.commit()
    db.add(
        InsiderActivity(
            cik=CIK,
            activity_type=insider_activity.FIRST_BUY,
            activity_date=D0,
            filing_date=D0,
            accession_number="0001-26-000002",
            owners="[]",
            detail="{}",
            source_url="x",
        )
    )  # the company is stored already
    db.commit()
    kinds = {r.activity_type for r in insider_activity.store(db, CIK, set(), start)}
    assert insider_activity.CLUSTER not in kinds  # an old cluster: held
    kinds = {r.activity_type for r in insider_activity.store(db, CIK, {third}, start)}
    assert insider_activity.CLUSTER in kinds  # formed by a new filing: stored
    assert insider_activity.HOLD_OLD_CLUSTERS is True  # the module's own value is now False


def test_signers_and_name_keys():
    """F-03d: a signature links only in a control capacity, never by attorney-in-fact or power of
    attorney; entity names link by their first two significant words."""
    s = insider_activity._signers
    assert s("Grafiti Group LLC By: Nadir Ali, as General Manager") == ["Nadir Ali"]
    assert s("Privet Fund Management LLC; By: /s/ Ryan Levenson, Managing Member") == [
        "Ryan Levenson"]  # fmt: skip
    for no in ("/s/ Robert Anderson by P.O.A. for Howard P. Feinglass, the managing member",
               "/s/ Victor Semah, as Attorney-in-Fact", "Saba Capital Management, L.P. By: Zachary",
               "/s/ Diane M. Stenson, Vice President, on behalf of Lilly Endowment Inc.",
               "UY Scuti Investments Limited, By: /s/ Guojian Zhang, Director"):  # fmt: skip
        assert s(no) == [], no
    k = insider_activity._name_key
    assert k("GENERAL ATLANTIC, L.P.") == k("GENERAL ATLANTIC GENPAR (BERMUDA), L.P.")
    assert k("ABRAMS CAPITAL MANAGEMENT, L.P.") is None  # one significant word
    assert k("General Atlantic") != k("General Catalyst Group")


def test_affiliates_filing_apart_are_one_buyer(db):
    """F-03d: a fund's two entity sets that never share a Form 4 (same name key), the individual
    who signs for the fund as managing member, and an entity a footnote names as the fund's sole
    member are one buyer; an attorney-in-fact and a namesake are not."""
    import json

    from app.db.models import InsiderFilingText

    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, start, "P", 100, 10)

    def entity(n, owner, name, day, sig="", notes=()):
        acc = _trade(db, n, owner, day, "P", 100, 10)
        db.execute(text_update(owner, name))
        db.add(InsiderFilingText(accession_number=acc, signatures=json.dumps([sig]),
                                 remarks=None, footnotes=json.dumps(list(notes)),
                                 source="test"))  # fmt: skip
        return acc

    def text_update(owner, name):
        from sqlalchemy import update

        db.flush()  # the owner's row first
        return update(InsiderFiling).where(InsiderFiling.owner_cik == f"{owner:010d}").values(
            owner_name=name, is_officer=False)  # fmt: skip

    entity(2, 31, "GENERAL ATLANTIC, L.P.", D0)
    entity(3, 32, "GENERAL ATLANTIC GENPAR (BERMUDA), L.P.", D0 + timedelta(days=1))
    entity(4, 41, "Privet Fund Management LLC", D0 + timedelta(days=2),
           sig="Privet Fund Management LLC By: /s/ Ryan Levenson, Managing Member")  # fmt: skip
    _trade(db, 5, 42, D0 + timedelta(days=3), "P", 100, 10)  # Ryan Levenson, himself
    entity(
        6,
        51,
        "ASOF Investment Management LLC",
        D0 + timedelta(days=4),
        notes=["The sole member of ASOF Investment Management is Ares Management LLC."],
    )
    entity(7, 52, "Ares Management LLC", D0 + timedelta(days=5))
    entity(8, 61, "Smith Capital LLC", D0 + timedelta(days=6),
           sig="Smith Capital LLC By: /s/ Jane Roe by P.O.A. for John Smith, the managing "
               "member of Smith Capital LLC")  # fmt: skip
    _trade(db, 9, 62, D0 + timedelta(days=7), "P", 100, 10)  # John Smith
    db.execute(text_update(42, "Levenson Ryan"))
    db.execute(text_update(62, "Smith John"))
    db.commit()
    g = insider_activity.buyers(insider_activity._trades(db, CIK),
                                insider_activity.affiliates(db, CIK))  # fmt: skip
    c = "{:010d}".format
    assert g[c(31)] == g[c(32)]  # name key
    assert g[c(41)] == g[c(42)]  # signs as managing member
    assert g[c(51)] == g[c(52)]  # named as sole member in a footnote
    assert g[c(61)] != g[c(62)]  # attorney-in-fact and a namesake: not linked


def test_a_new_entity_form4_stores_its_text(db):
    """F-03e: a Form 4 read as filed (the tracker's ingest) stores its signatures, remarks and
    footnotes when a reporting owner is an entity, so affiliate linking keeps working after the
    data sets; an individual's Form 4 stores none."""
    import json
    from pathlib import Path

    from app.db.models import InsiderFilingText
    from app.services import insiders

    xml = (Path(__file__).parents[1] / "fixtures" / "connections" / "form4_aapl.xml").read_text()
    person = insiders.parse_ownership_xml(xml, "0001140361-26-000001", date(2026, 11, 12))
    insiders.store(db, person, "filing")
    fund = xml.replace("Newstead Jennifer", "Newstead Capital LLC")
    parsed = insiders.parse_ownership_xml(fund, "0001140361-26-000002", date(2026, 11, 12))
    insiders.store(db, parsed, "filing")
    db.commit()
    assert db.get(InsiderFilingText, "0001140361-26-000001") is None
    t = db.get(InsiderFilingText, "0001140361-26-000002")
    assert t is not None and t.source == "filing"
    assert json.loads(t.signatures) == [
        "/s/ Sam Whittington, Attorney-in-Fact for Jennifer Newstead"]  # fmt: skip
    assert json.loads(t.footnotes)[0].startswith("This transaction was made pursuant to a Rule")


def test_a_plan_purchase_is_never_in_a_cluster_or_a_first_buy(db):
    """F-03f: shares bought by an ESPP trust or through dividend reinvestment are not open-market
    buys (TSMC's 6 Nov: 48 and 57 shares 'By ESPP Trust' made a cluster): never a cluster's buyer
    or a first buy. A stored cluster that counted them is retracted with its reason."""
    import json

    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, D0, "P", 48, 76)
    _trade(db, 2, 2, D0 + timedelta(days=1), "P", 57, 76)
    _trade(db, 3, 3, D0 + timedelta(days=2), "P", 5000, 75)  # the one open-market buy
    db.commit()
    for n in (1, 2):
        db.scalar(select(InsiderTransaction).where(
            InsiderTransaction.row_key == f"{n}")).plan_purchase = True  # fmt: skip
    db.commit()
    kinds = [(a["type"], a["trade"].accession) for a in insider_activity.detect(db, CIK, start)]
    assert insider_activity.CLUSTER not in {k for k, _ in kinds}
    assert {a for k, a in kinds if k == insider_activity.FIRST_BUY} == {"0001-26-000003"}
    before = insider_activity.detect(db, CIK, start, plan=False)  # as stored before F-03f
    now = utcnow()
    for a in before:
        t = a["trade"]
        db.add(InsiderActivity(cik=CIK, activity_type=a["type"], activity_date=t.trans_date,
                               filing_date=t.filing_date, accession_number=t.accession,
                               owners=json.dumps(a["owners"]), detail=json.dumps(a["detail"]),
                               source_url="https://www.sec.gov/Archives/x",
                               stream_status="published", stream_at=now))  # fmt: skip
    db.commit()
    n = db.scalar(select(func.count()).select_from(InsiderActivity))
    acts = insider_activity.reconcile(db, CIK, start, write=True, now=now,
                                      before_rules={"plan": False},
                                      reason="a plan purchase")  # fmt: skip
    db.commit()
    assert {(a["action"], a["key"][0]) for a in acts} >= {("retract", insider_activity.CLUSTER)}
    assert db.scalar(select(func.count()).select_from(InsiderActivity)) == n  # nothing deleted
    cl = db.scalar(select(InsiderActivity).where(
        InsiderActivity.activity_type == insider_activity.CLUSTER))  # fmt: skip
    assert cl.status == "retracted" and cl.retraction_reason == "a plan purchase"


def test_plan_purchases_are_read_from_ownership_text_and_the_lines_own_footnotes():
    """F-03f detection, as filed: an ESPP trust, an ESPP administrator buying in the open market
    (Kingsway), a broker's dividend reinvestment; not a 10b5-1 'stock purchase plan', a note
    that 'includes' other plan shares, a 401(k) account, or a footnote on the holding after."""
    from app.services import insiders

    p = insiders.plan_purchase
    assert p("P", "By ESPP Trust", []) and p("S", "By ESPP Trust", []) is None
    assert p("P", None, ["Acquired pursuant to the Kingsway America Inc. Employee Share Purchase "
                         "Plan; the administrator buys shares in the open market."])  # fmt: skip
    assert p("P", None, ["Shares purchased pursuant to a broker-sponsored dividend reinvestment "
                         "program."])  # fmt: skip
    assert not p("P", None, ["Made pursuant to a previously-disclosed Rule 10b5-1 stock purchase "
                             "plan adopted by the reporting person."])  # fmt: skip
    assert not p("P", None, ["Includes 945 shares acquired through dividend reinvestment."])
    assert not p("P", "By 401(k)", [])
    xml = """<ownershipDocument><documentType>4</documentType>
      <issuer><issuerCik>0001046179</issuerCik></issuer><periodOfReport>2026-11-06</periodOfReport>
      <reportingOwner><reportingOwnerId><rptOwnerCik>0000000001</rptOwnerCik>
        <rptOwnerName>A</rptOwnerName></reportingOwnerId></reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
          <transactionDate><value>2026-11-06</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode><footnoteId id="F1"/>
          </transactionCoding>
          <transactionAmounts><transactionShares><value>48</value></transactionShares>
          </transactionAmounts></nonDerivativeTransaction>
        <nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
          <transactionDate><value>2026-11-06</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts><transactionShares><value>5000</value></transactionShares>
          </transactionAmounts>
          <postTransactionAmounts><sharesOwnedFollowingTransaction><value>9000</value>
            <footnoteId id="F2"/></sharesOwnedFollowingTransaction></postTransactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
      <footnotes><footnote id="F1">Purchased by the administrator of the issuer's Employee Stock
        Purchase Plan.</footnote><footnote id="F2">300 of these shares are held in the
        reporting person's ESPP account.</footnote></footnotes></ownershipDocument>"""
    rows = insiders.parse_ownership_xml(xml, "0001046179-26-000001", date(2026, 11, 7)).rows
    assert [r["plan_purchase"] for r in rows] == [True, False]


def test_an_inferred_plan_purchase_is_never_in_a_cluster_or_a_first_buy(db):
    """F-03g: a purchase of a fraction of a share under 100 shares, with no plan stated, is
    likely dividend reinvestment or a plan (inferred, never plan_purchase): never a cluster's
    buyer or a first buy. A cluster that counted one is retracted with its reason."""
    import json

    from app.services import insiders

    assert insiders.plan_inferred("P", Decimal("22.22"), False) is True
    assert insiders.plan_inferred("P", Decimal("22.22"), True) is False  # stated already
    assert insiders.plan_inferred("P", Decimal("183.53"), False) is False  # 100 or more
    assert insiders.plan_inferred("P", Decimal("48"), False) is False  # whole shares
    assert insiders.plan_inferred("S", Decimal("2.5"), False) is None
    _company(db)
    start = D0 - timedelta(days=900)
    _trade(db, 1, 1, D0, "P", 5000, 30)
    _trade(db, 2, 2, D0 + timedelta(days=1), "P", 2000, 30)
    _trade(db, 3, 3, D0 + timedelta(days=2), "P", "22.22", 30)  # a reinvested dividend
    db.commit()
    db.scalar(select(InsiderTransaction).where(
        InsiderTransaction.row_key == "3")).plan_inferred = True  # fmt: skip
    db.commit()
    kinds = {a["type"] for a in insider_activity.detect(db, CIK, start)}
    assert insider_activity.CLUSTER not in kinds
    assert insider_activity.CLUSTER in {
        a["type"] for a in insider_activity.detect(db, CIK, start, inferred=False)
    }
    for a in insider_activity.detect(db, CIK, start, inferred=False):
        t = a["trade"]
        db.add(InsiderActivity(cik=CIK, activity_type=a["type"], activity_date=t.trans_date,
                               filing_date=t.filing_date, accession_number=t.accession,
                               owners=json.dumps(a["owners"]), detail=json.dumps(a["detail"]),
                               source_url="https://www.sec.gov/Archives/x",
                               stream_status="published", stream_at=utcnow()))  # fmt: skip
    db.commit()
    insider_activity.reconcile(db, CIK, start, write=True, before_rules={"inferred": False},
                               reason="inferred plan purchase")  # fmt: skip
    db.commit()
    cl = db.scalar(select(InsiderActivity).where(
        InsiderActivity.activity_type == insider_activity.CLUSTER))  # fmt: skip
    assert cl.status == "retracted" and cl.retraction_reason == "inferred plan purchase"
