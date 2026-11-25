"""Q-03: the cross-company insider screener (docs/contracts/insider-screener.md)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Company, InsiderActivity, InsiderFiling, InsiderTransaction, utcnow
from app.services.insider_activity import CLUSTER

DEMO = {"X-API-Key": "demo"}
A, B, C = "0002999101", "0002999102", "0002999103"
URL = "/v1/insider-transactions"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/"


def _filing(db, acc, issuer, owner, name, filed, form="4", period=None, plan=None, **roles):
    db.add(InsiderFiling(accession_number=acc, issuer_cik=issuer, owner_cik=owner, owner_name=name,
                         is_director=roles.get("director", False),
                         is_officer=roles.get("officer", False),
                         is_ten_percent_owner=roles.get("ten", False), is_other=False,
                         officer_title=roles.get("title"), form_type=form, filing_date=filed,
                         period_of_report=period or filed, plan_10b5_1=plan,
                         source="test"))  # fmt: skip


def _line(db, acc, issuer, n, code, day, shares, price, after=None, title="Common Stock",
          di="D"):  # fmt: skip
    db.add(InsiderTransaction(accession_number=acc, issuer_cik=issuer, row_kind="transaction",
                              is_derivative=False, row_key=f"{acc}-{n}", security_title=title,
                              trans_date=day, trans_code=code,
                              shares=Decimal(str(shares)) if shares is not None else None,
                              price=Decimal(str(price)) if price is not None else None,
                              shares_after=Decimal(str(after)) if after is not None else None,
                              direct_indirect=di))  # fmt: skip


@pytest.fixture
def trades(db):
    now = utcnow()
    for cik, name, tick in ((A, "Alder Example Corp", "ALDR"), (B, "Birch Example Inc.", None),
                            (C, "Cedar Example Holdings", "CDR")):  # fmt: skip
        db.add(Company(cik=cik, legal_name=name, ticker=tick, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now))  # fmt: skip
    d = date
    # A: the CEO sells Class A and Class C on one Form 4 (two rows), under a 10b5-1 plan
    _filing(db, "0000000001-26-000001", A, "0000000101", "SMITH JANE", d(2026, 11, 10),
            plan=True, officer=True, title="Chief Executive Officer")  # fmt: skip
    _line(db, "0000000001-26-000001", A, 1, "S", d(2026, 11, 6), 1000, 100, 9000,
          "Class A Common Stock")  # fmt: skip
    _line(db, "0000000001-26-000001", A, 2, "S", d(2026, 11, 7), 3000, 104, 6000,
          "Class A Common Stock")  # fmt: skip
    _line(db, "0000000001-26-000001", A, 3, "S", d(2026, 11, 7), 500, 98, 2000,
          "Class C Capital Stock")  # fmt: skip
    # A: its 4/A (same owner, same period): never a row, listed on the original
    _filing(db, "0000000001-26-000002", A, "0000000101", "SMITH JANE", d(2026, 11, 12),
            form="4/A", period=d(2026, 11, 10), plan=True, officer=True,
            title="Chief Executive Officer")  # fmt: skip
    _line(db, "0000000001-26-000002", A, 1, "S", d(2026, 11, 6), 1000, 100, 9000,
          "Class A Common Stock")  # fmt: skip
    # B: a director buys; one line unpriced (value partial); direct and indirect lines mixed
    _filing(db, "0000000002-26-000001", B, "0000000201", "DOE JOHN", d(2026, 11, 3), plan=False,
            director=True)  # fmt: skip
    _line(db, "0000000002-26-000001", B, 1, "P", d(2026, 11, 2), 2000, 10, 12000)
    _line(db, "0000000002-26-000001", B, 2, "P", d(2026, 11, 2), 500, None, 4000, di="I")
    # B: two more directors buy: a cluster (F-03 event at the third purchase)
    _filing(db, "0000000002-26-000002", B, "0000000202", "ROE RICHARD", d(2026, 11, 4),
            director=True)  # fmt: skip
    _line(db, "0000000002-26-000002", B, 1, "P", d(2026, 11, 3), 100, 10, 1100)
    _filing(db, "0000000002-26-000003", B, "0000000203", "POE ANN", d(2026, 11, 5), director=True)
    _line(db, "0000000002-26-000003", B, 1, "P", d(2026, 11, 4), 100, 10, 100)
    db.add(InsiderActivity(cik=B, activity_type=CLUSTER, activity_date=d(2026, 11, 4),
                           filing_date=d(2026, 11, 5), accession_number="0000000002-26-000003",
                           owners=json.dumps([{"owner_cik": o, "name": "x", "role": "Director"}
                                              for o in ("0000000201", "0000000202",
                                                        "0000000203")]),
                           detail=json.dumps({"insiders": 3, "days": 30,
                                              "first_trade": "2026-11-02"}),
                           source_url=f"{ARCHIVES}2999102/x/"))  # fmt: skip
    # C: an as-filed date error (after its own filing) and a price outlier (total in the box)
    _filing(db, "0000000003-26-000001", C, "0000000301", "LEE AMY", d(2026, 11, 1), officer=True,
            title="CFO")  # fmt: skip
    _line(db, "0000000003-26-000001", C, 1, "S", d(2026, 11, 20), 100, 20, 900)
    for i, day in enumerate((d(2026, 11, 2), d(2026, 11, 3), d(2026, 11, 4), d(2026, 11, 5))):
        acc = f"0000000003-26-00001{i}"
        _filing(db, acc, C, "0000000302", "KIM BO", day, officer=True, title="EVP and CFO")
        _line(db, acc, C, 1, "S", day, 100, 20 if i < 3 else 20 * 5000, 1000)
    # C: an unpaired 4/A (no original stored)
    _filing(db, "0000000003-26-000099", C, "0000000303", "NOVAK EVE", d(2026, 11, 6), form="4/A",
            period=d(2026, 11, 1))  # fmt: skip
    _line(db, "0000000003-26-000099", C, 1, "S", d(2026, 11, 1), 50, 20, 0)
    db.commit()


def _get(client, auth, **params):
    params.setdefault("since", "2026-10-25")
    params.setdefault("until", "2026-11-24")
    params = {k: v for k, v in params.items() if v is not None}
    return client.get(URL, params=params, headers=auth)


def _key(r):
    return (r["filing"]["accession_number"], r["trans_code"], r["security_title"])


def test_rows_per_form4_code_and_class(client, auth, db, trades):
    body = _get(client, auth, cik=A).json()
    rows = {r["security_title"]: r for r in body["data"]}
    assert set(rows) == {"Class A Common Stock", "Class C Capital Stock"}  # never summed
    a = rows["Class A Common Stock"]
    assert (a["shares"], a["lines"], a["value"]) == (4000, 2, 412000)
    assert a["average_price"] == 103 and a["value_partial"] is False
    assert (a["first_date"], a["last_date"]) == ("2026-11-06", "2026-11-07")
    assert a["shares_after"] == 6000 and a["holdings_change_pct"] == -40.0
    assert a["plan_10b5_1"] is True and a["type"] == "sell"
    assert a["owners"][0]["name"] == "Jane Smith" and a["issuer"]["ticker"] == "ALDR"
    assert a["filing"]["form"] == "4"
    assert a["filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    # the 4/A is no row; the original lists it
    assert all(r["filing"]["form"] == "4" for r in body["data"])
    assert [x["accession_number"] for x in a["amended_by"]] == ["0000000001-26-000002"]
    assert body["labels"]["disclaimer"] == "Information, not signals. Not investment advice."
    raw = str(body)
    for banned in ("first_detected_at", "source_updated_at", "cusip", "data.sec.gov"):
        assert banned not in raw


def test_partial_prices_mixed_holdings_clusters(client, auth, db, trades):
    rows = {r["filing"]["accession_number"]: r for r in _get(client, auth, cik=B).json()["data"]}
    first = rows["0000000002-26-000001"]
    assert first["value"] == 20000 and first["value_partial"] is True
    assert first["average_price"] == 10  # priced lines only
    assert first["direct_indirect"] == "mixed" and first["holdings_change_pct"] is None
    assert {k for k, r in rows.items() if r["cluster"]} == set(rows)
    assert rows["0000000002-26-000003"]["cluster"]["insiders"] == 3
    only = _get(client, auth, cluster="true").json()["data"]
    assert {r["issuer"]["cik"] for r in only} == {B}
    bad = _get(client, auth, cluster="true", type="sell")
    assert bad.status_code == 422


def test_filed_errors_outliers_and_unpaired_amendments(client, auth, db, trades):
    body = _get(client, auth, cik=C).json()
    accs = {r["filing"]["accession_number"] for r in body["data"]}
    assert "0000000003-26-000001" not in accs  # dated after its own filing
    assert "0000000003-26-000099" not in accs  # an amendment
    notes = " ".join(body["notes"])
    assert "1 line dated after" in notes and "1 amended filing" in notes
    out = {r["filing"]["accession_number"]: r for r in body["data"]}
    assert out["0000000003-26-000013"]["price_outlier"] is True
    assert out["0000000003-26-000013"]["value"] == 10_000_000  # shown as filed
    ranked = _get(client, auth, cik=C, sort="value").json()["data"]
    assert ranked[-1]["filing"]["accession_number"] == "0000000003-26-000013"  # last
    big = _get(client, auth, cik=C, min_value=1000).json()["data"]
    assert "0000000003-26-000013" not in {r["filing"]["accession_number"] for r in big}


def test_filters_sort_and_pages(client, auth, db, trades):
    buys = _get(client, auth, type="buy").json()["data"]
    assert {r["trans_code"] for r in buys} == {"P"}
    ceo_cfo = _get(client, auth, title="chief executive,cfo", type="sell").json()["data"]
    assert {r["issuer"]["cik"] for r in ceo_cfo} == {A, C}
    assert _get(client, auth, title="cf").json()["data"] == []  # whole words only
    directors = _get(client, auth, role="director").json()["data"]
    assert {r["issuer"]["cik"] for r in directors} == {B}
    planned = _get(client, auth, plan_10b5_1="true").json()["data"]
    assert {r["issuer"]["cik"] for r in planned} == {A}
    assert {r["issuer"]["cik"] for r in _get(client, auth, owner_cik="201").json()["data"]} == {B}
    # as_of: nothing filed later; until follows it
    early = _get(client, auth, as_of="2026-11-04", since="2026-10-25", until=None).json()
    assert {r["filing"]["accession_number"] for r in early["data"]} <= {
        "0000000002-26-000001", "0000000002-26-000002", "0000000003-26-000010",
        "0000000003-26-000011", "0000000003-26-000012"}  # fmt: skip
    assert early["filters"]["until"] == "2026-11-04"
    page = _get(client, auth, limit=2).json()
    assert page["meta"] == {"limit": 2, "offset": 0, "has_more": True, "next_offset": 2}
    dates = [r["last_date"] for r in _get(client, auth).json()["data"]]
    assert dates == sorted(dates, reverse=True)
    values = [r["value"] for r in _get(client, auth, sort="value", type="buy").json()["data"]]
    assert values == sorted(values, reverse=True)


def test_errors(client, auth, db, trades):
    for params in ({"since": "2025-01-01", "until": "2026-11-24"},
                   {"since": "2026-11-24", "until": "2026-11-01"},
                   {"role": "chair"}, {"title": "x" * 41}, {"title": ",".join("abcdefg")},
                   {"min_value": 10, "max_value": 5}, {"cik": "abc"}):  # fmt: skip
        r = _get(client, auth, **params)
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameter", params


def test_demo_key_showcase_and_trim(client, db, trades, settings, monkeypatch):
    monkeypatch.setattr(settings, "public_showcase_ciks", f"{A},{C}")
    params = {"since": "2026-10-25", "until": "2026-11-24", "limit": 20}
    body = client.get(URL, params=params, headers=DEMO).json()
    assert body["meta"]["limit"] == 10
    assert {r["issuer"]["cik"] for r in body["data"]} <= {A, C}
    r = client.get(URL, params={**params, "cik": B}, headers=DEMO)
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_scope"


def test_mcp_screen_insider_trades(client, auth, db, trades):
    args = {"type": "buy", "cluster": True, "since": "2026-10-25", "until": "2026-11-24"}
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "screen_insider_trades", "arguments": args}}  # fmt: skip
    res = client.post("/mcp", json=body, headers=auth).json()["result"]
    assert res["isError"] is False
    out = json.loads(res["content"][0]["text"])
    assert {r["issuer"]["cik"] for r in out["data"]} == {B} and out["labels"]["disclaimer"]


def test_chat_insider_questions(client, auth, db, trades, monkeypatch):
    from datetime import date as real_date

    from app.services import conversation as cv

    today = real_date(2026, 11, 24)
    f = cv.insider_screen_request("Which insiders bought over $1M last month?", today)
    assert (f["type"], f["min_value"], f["cluster"]) == ("buy", 1e6, False)
    f = cv.insider_screen_request("CEO and CFO sales this week", today)
    assert f["type"] == "sell" and set(f["titles"]) == {"ceo", "chief executive", "cfo",
                                                         "chief financial"}  # fmt: skip
    assert cv.insider_screen_request("Cluster buying in the last 30 days", today)["cluster"]
    for other in ("Who is the CEO of Tesla?", "What were Apple's sales last year?",
                  "Which companies filed a 10-K last month?"):  # fmt: skip
        assert cv.insider_screen_request(other, today) is None, other

    class Today(real_date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(cv, "date", Today)
    q = "Which insiders made cluster buying purchases in the last 30 days?"
    r = client.post("/v1/chat", json={"message": q}, headers=auth).json()
    assert r["intent"] == "insider_screen"
    (table,) = [w for w in r["widgets"] if w["type"] == "table"]
    assert {row[0]["text"] for row in table["rows"]} == {"Birch Example Inc."}
    assert table["rows"][0][8]["url"].startswith("https://www.sec.gov/Archives/")
    assert "Information, not signals" in r["answer"] and r["citations"]
    # on a company page the company's own insiders answer, not the screen
    own = client.post("/v1/chat", json={"message": "How much did the CEO sell?", "cik": A},
                      headers=auth).json()  # fmt: skip
    assert own["intent"] != "insider_screen"


def test_a_form4_filed_twice_the_same_day_counts_once(client, auth, db, trades):
    for acc in ("0000000004-26-000001", "0000000004-26-000002"):
        _filing(db, acc, C, "0000000401", "PARK SAM", date(2026, 11, 8), officer=True,
                title="COO")  # fmt: skip
        _line(db, acc, C, 1, "P", date(2026, 11, 7), 9000, 20, 10000)
    db.commit()
    body = _get(client, auth, cik=C, type="buy").json()
    rows = [r for r in body["data"] if r["owners"][0]["cik"] == "0000000401"]
    assert len(rows) == 1 and rows[0]["filing"]["accession_number"] == "0000000004-26-000001"
    assert [d["accession_number"] for d in rows[0]["duplicate_filings"]] == [
        "0000000004-26-000002"]  # fmt: skip
    assert "Shown once: 1 Form 4 filed again" in " ".join(body["notes"])


def test_class_names_lose_the_data_sets_csv_quoting(client, auth, db, trades):
    _filing(db, "0000000005-26-000001", C, "0000000501", "WU LI", date(2026, 11, 9))
    _line(db, "0000000005-26-000001", C, 1, "S", date(2026, 11, 9), 10, 20, 90,
          '"Class A Common Stock (""Common Stock"")"')  # fmt: skip
    db.commit()
    (row,) = [r for r in _get(client, auth, owner_cik="501").json()["data"]]
    assert row["security_title"] == 'Class A Common Stock ("Common Stock")'
    assert row["shares_after"] == 90 and "_title" not in row


def test_price_outlier_is_per_class_local_and_stable(client, auth, db, trades):
    """PM review: the median is per issuer and class, within 30 days of the row's trades, so
    share classes and a reverse split never trip it, and the query's dates do not change it."""
    D = "0002999104"
    db.add(Company(cik=D, legal_name="Dogwood Example Holdings", source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), last_processed_at=utcnow()))  # fmt: skip
    n = 0

    def sale(day, price, title, shares=10):
        nonlocal n
        n += 1
        acc = f"0000000006-26-{n:06d}"
        _filing(db, acc, D, f"0000000{600 + n}", f"OWNER{n} X", day, officer=True, title="VP")
        _line(db, acc, D, 1, "S", day, shares, price, 1000, title)
        return acc

    for i in range(4):  # Class A near $700k, Class B near $470, the same days
        sale(date(2026, 11, 2 + i), 700_000 + i, "Class A Common Stock")
        sale(date(2026, 11, 2 + i), 470 + i, "Class B Common Stock")
    for i in range(4):  # before a 1:50 reverse split, more than 30 days earlier, at $2
        sale(date(2026, 9, 1 + i), 2, "Common Stock")
    for i in range(4):  # after it, at $100
        sale(date(2026, 11, 10 + i), 100 + i, "Common Stock")
    typo = sale(date(2026, 11, 14), 1_000_000, "Common Stock")  # the total in the price box
    db.commit()

    def flags(since, until):
        body = _get(client, auth, cik=D, since=since, until=until, limit=100).json()
        return {r["filing"]["accession_number"]: r["price_outlier"] for r in body["data"]}

    year, month = flags("2026-01-01", "2026-11-24"), flags("2026-11-01", "2026-11-24")
    assert {a for a, f in year.items() if f} == {typo}
    assert {a for a, f in month.items() if f} == {typo}


def test_a_giant_value_needs_a_year_of_prices_behind_it(client, auth, db, trades):
    """PM decision: a row worth $5B or more is flagged unless 4+ same-class lines within a year
    have a median price within 20x: a single preferred line of 40M shares at $40M is."""
    _filing(db, "0000000007-26-000001", C, "0000000701", "FUND BIG", date(2026, 11, 9))
    _line(db, "0000000007-26-000001", C, 1, "S", date(2026, 11, 9), 40_000_000, 40_000_000, 0,
          "5.364% Series A Preferred")  # fmt: skip
    _filing(db, "0000000007-26-000002", A, "0000000702", "HOLDER LONG", date(2026, 11, 9))
    _line(db, "0000000007-26-000002", A, 1, "S", date(2026, 11, 9), 50_000_000, 120, 0,
          "Class A Common Stock")  # fmt: skip  # $6B, backed by a year of prices
    for i in range(4):
        _filing(db, f"0000000007-26-00001{i}", A, "0000000703", "TRADER T", date(2026, 3, 2 + i))
        _line(db, f"0000000007-26-00001{i}", A, 1, "S", date(2026, 3, 2 + i), 10, 110 + i, 0,
              "Class A Common Stock")  # fmt: skip
    db.commit()
    rows = {r["filing"]["accession_number"]: r
            for r in _get(client, auth, since="2026-01-01", limit=100).json()["data"]}  # fmt: skip
    assert rows["0000000007-26-000001"]["price_outlier"] is True
    assert rows["0000000007-26-000002"]["price_outlier"] is False


def test_title_forms_that_are_not_the_officer_and_matching_owner_first(client, auth, db, trades):
    from app.services.insider_screener import _title_match

    t = ["chief executive", "chief financial", "ceo", "cfo"]
    for title in ("Strategic Advisor to CEO", "SVP & Advisor to the CFO", "Global COO & Deputy CEO",
                  "Chief Executive Assistant", "Executive Assistant to the CEO"):  # fmt: skip
        assert not _title_match(t, title), title
    for title in ("CEO", "President & CEO", "EVP & CFO", "CHIEF EXECUTIVE OFF."):
        assert _title_match(t, title), title
    # a joint Form 4: the owner that matches the title is listed first
    acc = "0000000008-26-000001"
    _filing(db, acc, C, "0000000801", "AARDVARK ANN", date(2026, 11, 9), officer=True,
            title="EVP - Business Operations")  # fmt: skip
    _filing(db, acc, C, "0000000899", "ZEBRA ZED", date(2026, 11, 9), officer=True, title="CEO")
    _line(db, acc, C, 1, "S", date(2026, 11, 9), 10, 20, 90)
    db.commit()
    body = _get(client, auth, title="ceo", cik=C).json()
    (row,) = [r for r in body["data"] if r["filing"]["accession_number"] == acc]
    assert row["owners"][0]["officer_title"] == "CEO"
    assert body["through"] == "2026-11-10" and "datasets_through" in body  # 4/A on 11-12 not


def test_role_ceo_cfo_is_the_companys_own_principal_officers(client, auth, db, trades):
    from app.services.insider_screener import principal_roles as pr

    yes = {"CEO": {"ceo"}, "Chairman, President and Chief Executive Officer": {"ceo"},
           "EVP & CFO": {"cfo"}, "Interim CEO": {"ceo"}, "Co-CEO": {"ceo"},
           "CEO ad interim": {"ceo"}, "SVP Finance, Treasurer, & CFO": {"cfo"},
           "E.V.P., CFO, CSO": {"cfo"}, "CFO and Assistant Secretary": {"cfo"},
           "Deputy CEO & CFO": {"cfo"}, "CEO, CFO and Secretary": {"ceo", "cfo"}}  # fmt: skip
    for title, want in yes.items():
        assert pr(title) == want, title
    for title in ("KFC Division CEO", "CEO, Medicare Advantage", "Chief Executive Officer, Optum",
                  "Group CEO", "Centennial Bank CEO", "Strategic Advisor to CEO",
                  "Chief Executive Assistant", "Former CFO", "CEO Designate", "CEO of Manager",
                  "Global COO & Deputy CEO", "President and CEO, Retail"):  # fmt: skip
        assert pr(title) == set(), title
    ceo = {r["issuer"]["cik"] for r in _get(client, auth, role="ceo").json()["data"]}
    cfo = {r["issuer"]["cik"] for r in _get(client, auth, role="cfo").json()["data"]}
    assert ceo == {A} and cfo == {C}  # Jane Smith, CEO of A; the CFOs of C


def test_a_4a_that_restates_the_row_shows_its_figures(client, auth, db, trades):
    """Q-03d: RB Global filed a price of $400 and corrected it to $94 on a 4/A. The row shows the
    4/A's figures (amended, the 4/A as its filing, the original in first_filed), the value
    filters use them; a partial 4/A (fewer lines) or one pairing with two rows changes nothing."""
    d, D, E = date, "0002999104", "0002999105"
    now = utcnow()
    for cik, name in ((D, "Dogwood Example Inc."), (E, "Elm Example Inc.")):
        db.add(Company(cik=cik, legal_name=name, ticker=None, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now))  # fmt: skip
    _filing(db, "0000000004-26-000001", D, "0000000401", "PARK LEE", d(2026, 11, 10),
            period=d(2026, 11, 9), director=True)  # fmt: skip
    _line(db, "0000000004-26-000001", D, 1, "S", d(2026, 11, 9), 100, 400, 900)
    _filing(db, "0000000004-26-000002", D, "0000000401", "PARK LEE", d(2026, 11, 12),
            form="4/A", period=d(2026, 11, 9), director=True)  # fmt: skip
    _line(db, "0000000004-26-000002", D, 1, "S", d(2026, 11, 9), 100, 94, 900)
    # E: one 4/A, two originals of the same owner and period: which it restates is unknown
    for n, shares in ((1, 300), (2, 700)):
        _filing(db, f"0000000005-26-00000{n}", E, "0000000501", "ROSS KAI", d(2026, 11, 10),
                period=d(2026, 11, 9), director=True)  # fmt: skip
        _line(db, f"0000000005-26-00000{n}", E, 1, "S", d(2026, 11, 9), shares, 10, 0)
    _filing(db, "0000000005-26-000009", E, "0000000501", "ROSS KAI", d(2026, 11, 12),
            form="4/A", period=d(2026, 11, 9), director=True)  # fmt: skip
    _line(db, "0000000005-26-000009", E, 1, "S", d(2026, 11, 9), 350, 10, 0)
    db.commit()
    body = _get(client, auth, cik=D).json()
    (r,) = body["data"]
    assert r["amended"] is True and (r["average_price"], r["value"]) == (94, 9400)
    assert r["filing"]["form"] == "4/A" and r["filing"]["accession_number"].endswith("000002")
    ff = r["first_filed"]
    assert (ff["average_price"], ff["value"], ff["shares"], ff["lines"]) == (400, 40000, 100, 1)
    assert ff["filing"]["accession_number"] == "0000000004-26-000001"
    assert ff["filing"]["form"] == "4"
    assert [a["accession_number"] for a in r["amended_by"]] == ["0000000004-26-000002"]
    assert any("show a 4/A's figures" in n for n in body["notes"])
    # the value filters use the figures shown, on either side of the correction
    assert [x["value"] for x in _get(client, auth, cik=D, max_value=10000).json()["data"]] == [9400]
    assert _get(client, auth, cik=D, min_value=30000).json()["data"] == []
    # A's 4/A has one of the original's two Class A lines: a partial correction, as first filed
    a = next(x for x in _get(client, auth, cik=A).json()["data"]
             if x["security_title"] == "Class A Common Stock")  # fmt: skip
    assert a["amended"] is False and a["first_filed"] is None and a["shares"] == 4000
    assert a["amended_by"]
    # E: the 4/A pairs with two rows: neither changes
    rows = _get(client, auth, cik=E).json()["data"]
    assert sorted(x["shares"] for x in rows) == [300, 700]
    assert not any(x["amended"] for x in rows)


def test_a_buy_cancelled_by_a_4a_is_never_a_cluster_buy(client, auth, db, trades):
    """Q-03d: a 4/A of 0 shares ("No such sale has occurred") cancels the purchase: the row stays
    (amended, 0 shares) but never carries a cluster, even though its owner is in the event."""
    _filing(db, "0000000002-26-000004", B, "0000000203", "POE ANN", date(2026, 11, 7),
            form="4/A", period=date(2026, 11, 5), director=True)  # fmt: skip
    _line(db, "0000000002-26-000004", B, 1, "P", date(2026, 11, 4), 0, 0, 0)
    db.commit()
    rows = {r["owners"][0]["cik"]: r for r in _get(client, auth, cik=B).json()["data"]}
    poe = rows["0000000203"]
    assert poe["amended"] is True and poe["shares"] == 0 and poe["cluster"] is None
    assert rows["0000000202"]["cluster"] is not None  # the others' purchases still count


def test_a_retracted_cluster_event_marks_no_row(client, auth, db, trades):
    """F-03c: a cluster event retracted after a rule correction no longer marks purchases."""
    from sqlalchemy import update

    assert any(r["cluster"] for r in _get(client, auth, cik=B).json()["data"])
    retract = {"status": "retracted", "retracted_at": utcnow(), "retraction_reason": "test"}
    db.execute(update(InsiderActivity).where(InsiderActivity.cik == B).values(**retract))
    db.commit()
    assert not any(r["cluster"] for r in _get(client, auth, cik=B).json()["data"])


def test_plan_purchases_are_marked_and_left_out_of_buys(client, auth, db, trades):
    """F-03f: a purchase by an ESPP trust is marked plan_purchase and left out of type=buy unless
    asked for (a note says so); open-market buys carry plan_purchase false, sales null."""
    _filing(db, "0000000002-26-000009", B, "0000000204", "TAN LEE", date(2026, 11, 9),
            officer=True, title="CFO")  # fmt: skip
    _line(db, "0000000002-26-000009", B, 1, "P", date(2026, 11, 7), 48, 76, 300)
    db.commit()
    db.query(InsiderTransaction).filter(
        InsiderTransaction.accession_number == "0000000002-26-000009").update(
        {"plan_purchase": True})  # fmt: skip
    db.commit()
    buys = _get(client, auth, type="buy", cik=B).json()
    accs = {r["filing"]["accession_number"] for r in buys["data"]}
    assert "0000000002-26-000009" not in accs and accs
    assert all(r["plan_purchase"] is False for r in buys["data"])
    assert any("stock purchase plan" in n for n in buys["notes"])
    plan = _get(client, auth, type="buy", cik=B, plan_purchase="true").json()["data"]
    assert [(r["filing"]["accession_number"], r["plan_purchase"]) for r in plan] == [
        ("0000000002-26-000009", True)]  # fmt: skip
    every = _get(client, auth, cik=B).json()["data"]
    assert "0000000002-26-000009" in {r["filing"]["accession_number"] for r in every}
    sells = _get(client, auth, type="sell", cik=A).json()["data"]
    assert sells and all(r["plan_purchase"] is None for r in sells)


def test_inferred_plan_purchases_are_marked_and_left_out_of_buys(client, auth, db, trades):
    """F-03g: a fractional purchase under 100 shares with no plan stated is plan_inferred (shown
    as "Likely plan purchase (not stated)"), left out of type=buy like a stated one."""
    _filing(db, "0000000002-26-000010", B, "0000000205", "ORR KIM", date(2026, 11, 9),
            director=True)  # fmt: skip
    _line(db, "0000000002-26-000010", B, 1, "P", date(2026, 11, 8), 22.22, 15, 900)
    db.commit()
    db.query(InsiderTransaction).filter(
        InsiderTransaction.accession_number == "0000000002-26-000010").update(
        {"plan_inferred": True, "plan_purchase": False})  # fmt: skip
    db.commit()
    buys = _get(client, auth, type="buy", cik=B).json()["data"]
    assert "0000000002-26-000010" not in {r["filing"]["accession_number"] for r in buys}
    assert all(r["plan_inferred"] is False for r in buys)
    plan = _get(client, auth, type="buy", cik=B, plan_purchase="true").json()["data"]
    (row,) = [r for r in plan if r["filing"]["accession_number"] == "0000000002-26-000010"]
    assert row["plan_inferred"] is True and row["plan_purchase"] is False
