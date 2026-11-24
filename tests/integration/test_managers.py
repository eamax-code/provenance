"""Q-02: Form 13F managers (docs/contracts/managers.md)."""

from __future__ import annotations

from datetime import date

import pytest

from app.db.models import (
    Company,
    Filing13F,
    Holding13F,
    IssuerCusip,
    ThirteenFIssuerName,
    ThirteenFReportedBy,
    utcnow,
)
from app.services import fund_managers as fm
from app.services import thirteenf

AAPL, NVDA, KO, XOM, UNM = "037833100", "67066G104", "191216100", "30231G102", "594918104"
Q1, Q2 = date(2024, 3, 31), date(2024, 6, 30)  # NVIDIA's reviewed 10:1 split: 2024-06-07
M1, M2, M3, M4, NT = "0000900001", "0000900002", "0000900003", "0000900004", "0000900005"
DEMO = {"X-API-Key": "demo"}


def _filing(db, acc, filer, name, period, filed, form="13F-HR", amendment=None):
    db.add(Filing13F(accession_number=acc, filer_cik=filer, filer_name=name, report_period=period,
                     filing_date=filed, form_type=form, amendment_type=amendment,
                     source="test"))  # fmt: skip


def _hold(db, acc, filer, cusip, period, filed, shares, value, title="COM"):
    db.add(Holding13F(accession_number=acc, cusip=cusip, filer_cik=filer, report_period=period,
                      filing_date=filed, title_of_class=title, shares=shares,
                      value_usd=value))  # fmt: skip


@pytest.fixture
def funds(db):
    now = utcnow()
    for cik, name, tick in (("0000320193", "Apple Inc.", "AAPL"),
                            ("0001045810", "NVIDIA CORP", "NVDA"),
                            ("0000021344", "COCA COLA CO", "KO"),
                            ("0000034088", "EXXON MOBIL CORP", "XOM"),
                            (M1, "Alpha Capital LLC", None)):  # fmt: skip
        db.add(Company(cik=cik, legal_name=name, ticker=tick, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now))  # fmt: skip
    for cusip, cik in ((AAPL, "0000320193"), (NVDA, "0001045810"), (KO, "0000021344"),
                       (XOM, "0000034088")):  # fmt: skip
        db.add(IssuerCusip(cusip=cusip, cik=cik, class_title="COM", method="test"))
    db.add(ThirteenFIssuerName(cusip=UNM, report_period=Q2, name="ACME WIDGETS PLC", managers=3,
                               share=1.0))  # fmt: skip
    f1, f2 = date(2024, 5, 10), date(2024, 8, 9)
    # M1, Alpha: Apple held, NVIDIA bought before the split (100 -> 1,500 after it: added),
    # Coca-Cola sold out, Acme (unmatched) new; a NEW HOLDINGS amendment adds Exxon
    _filing(db, "0000900001-24-000001", M1, "Alpha Capital LLC", Q1, f1)
    _hold(db, "0000900001-24-000001", M1, AAPL, Q1, f1, 1000, 170_000)
    _hold(db, "0000900001-24-000001", M1, NVDA, Q1, f1, 100, 90_000)
    _hold(db, "0000900001-24-000001", M1, KO, Q1, f1, 500, 30_000)
    _hold(db, "0000900001-24-000001", M1, UNM, Q1, f1, 200, 8_000, "GLOBAL TR UNITS")  # reworded
    _filing(db, "0000900001-24-000002", M1, "Alpha Capital LLC", Q2, f2)
    _hold(db, "0000900001-24-000002", M1, AAPL, Q2, f2, 1000, 210_000)
    _hold(db, "0000900001-24-000002", M1, NVDA, Q2, f2, 1500, 185_000)
    _hold(db, "0000900001-24-000002", M1, UNM, Q2, f2, 300, 12_000, "SHS")
    _filing(db, "0000900001-24-000003", M1, "Alpha Capital LLC", Q2, date(2024, 8, 20),
            "13F-HR/A", "NEW HOLDINGS")  # fmt: skip
    _hold(db, "0000900001-24-000003", M1, XOM, Q2, date(2024, 8, 20), 200, 23_000)
    # M2, Beta: a restatement replaces its first Q2 filing; it holds NVIDIA both quarters
    _filing(db, "0000900002-24-000001", M2, "Beta Partners LP", Q1, f1)
    _hold(db, "0000900002-24-000001", M2, NVDA, Q1, f1, 1000, 900_000)
    _hold(db, "0000900002-24-000001", M2, AAPL, Q1, f1, 10, 1_700)
    _filing(db, "0000900002-24-000002", M2, "Beta Partners LP", Q2, f2)
    _hold(db, "0000900002-24-000002", M2, NVDA, Q2, f2, 1, 1)  # a broken first filing
    _filing(db, "0000900002-24-000003", M2, "Beta Partners LP", Q2, date(2024, 8, 30),
            "13F-HR/A", "RESTATEMENT")  # fmt: skip
    _hold(db, "0000900002-24-000003", M2, NVDA, Q2, date(2024, 8, 30), 9000, 1_110_000)
    _hold(db, "0000900002-24-000003", M2, AAPL, Q2, date(2024, 8, 30), 10, 2_100)
    # M3: still reports thousands in 2024 (values 1/1,000 of everyone else's)
    _filing(db, "0000900003-24-000001", M3, "Gamma Trust Co", Q1, f1)
    _hold(db, "0000900003-24-000001", M3, AAPL, Q1, f1, 100, 17)
    _filing(db, "0000900003-24-000002", M3, "Gamma Trust Co", Q2, f2)
    _hold(db, "0000900003-24-000002", M3, AAPL, Q2, f2, 100, 21, "CAP STK CL A")  # its own words
    _hold(db, "0000900003-24-000002", M3, NVDA, Q2, f2, 50, 6)
    # M4 holds Apple in both quarters (a third price for the median)
    for acc, q, f, v in (("0000900004-24-000001", Q1, f1, 17_000),
                         ("0000900004-24-000002", Q2, f2, 21_000)):  # fmt: skip
        _filing(db, acc, M4, "Delta Advisors", q, f)
        _hold(db, acc, M4, AAPL, q, f, 100, v)
    # ...and NVIDIA across the split: 100 before, 1,000.4 after (fractional shares, not a buy)
    _hold(db, "0000900004-24-000001", M4, NVDA, Q1, f1, 100, 90_000)
    _hold(db, "0000900004-24-000002", M4, NVDA, Q2, f2, 1000.4, 123_400)
    # a 13F notice only, naming Alpha (files holdings) and an adviser that files none here
    _filing(db, "0000900005-24-000001", NT, "Notice Holdings", Q2, f2, "13F-NT")
    db.add(ThirteenFReportedBy(accession_number="0000900005-24-000001", seq=1, cik=M1,
                               file_number="028-00001", name="ALPHA CAPITAL LLC"))  # fmt: skip
    db.add(ThirteenFReportedBy(accession_number="0000900005-24-000001", seq=2, cik=None,
                               file_number="028-00002", name="Elsewhere Advisers Ltd"))  # fmt: skip
    db.commit()
    thirteenf.mark_loaded_through(db, date(2024, 8, 31))  # the latest complete quarter: Q2
    db.commit()
    for q in (Q1, Q2):
        fm.build_stats(db, q)
    fm.build_activity(db, Q2)


def _get(client, auth, path, **params):
    return client.get(path, params=params, headers=auth)


def test_portfolio_groups_compares_and_lists_exits(client, auth, db, funds):
    body = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-06-30").json()
    pos = {(p["issuer"]["cik"] or p["issuer"]["name"], p["class_label"]): p
           for p in body["positions"]}  # fmt: skip
    assert set(pos) == {("0000320193", "Common stock"), ("0001045810", "Common stock"),
                        ("ACME WIDGETS PLC", "Ordinary shares"),
                        ("0000034088", "Common stock")}  # fmt: skip
    assert pos[("0000320193", "Common stock")]["change"]["status"] == "unchanged"
    nv = pos[("0001045810", "Common stock")]["change"]
    assert nv["split_adjusted"] is True and nv["split"] == "10:1"
    assert (nv["status"], nv["shares_previous"]) == ("added", 1000)
    acme = pos[("ACME WIDGETS PLC", "Ordinary shares")]
    assert acme["issuer"]["cik"] is None
    # its title went from "GLOBAL TR UNITS" to "SHS": the same security, added, not new + exited
    assert (acme["change"]["status"], acme["change"]["shares_previous"]) == ("added", 200)
    assert pos[("0000034088", "Common stock")]["change"]["status"] == "new"
    assert [x["issuer"]["cik"] for x in body["exited"]] == ["0000021344"]
    assert body["filing"]["amendments"][0]["amendment_type"] == "NEW HOLDINGS"
    assert body["totals"]["value_usd"] == 430_000 and body["totals"]["matched_positions"] == 3
    assert body["manager"]["company_cik"] == M1
    assert body["value_basis"] == "usd" and "45 days" in body["reporting_lag"]
    assert body["labels"]["disclaimer"].startswith("Information, not signals")
    assert any("10:1 split" in n for n in body["notes"])
    assert [h["quarter"] for h in body["history"]] == ["2024-06-30", "2024-03-31"]
    raw = str(body)
    for banned in (AAPL, NVDA, UNM, "cusip", "data.sec.gov"):
        assert banned not in raw.replace("cusips", "")


def test_restatement_replaces_and_exits_need_a_filing(client, auth, db, funds):
    body = _get(client, auth, f"/v1/managers/{M2}", quarter="2024-06-30").json()
    nv = next(p for p in body["positions"] if p["issuer"]["cik"] == "0001045810")
    assert nv["shares"] == 9000  # the restatement, not the broken first filing
    assert body["filing"]["accession_number"] == "0000900002-24-000003"
    assert body["filing"]["amendment_type"] == "RESTATEMENT"
    assert body["filing"]["replaces"]["accession_number"] == "0000900002-24-000002"
    assert body["notice_only"] is False


def test_a_filing_still_in_thousands_is_flagged_not_scaled(client, auth, db, funds):
    body = _get(client, auth, f"/v1/managers/{M3}", quarter="2024-06-30").json()
    assert body["filing"]["value_scale_suspect"] is True
    assert body["totals"]["value_usd"] is None
    assert all(p["pct_of_portfolio"] is None for p in body["positions"])
    assert {p["value_usd"] for p in body["positions"]} == {21, 6}  # as filed
    # one manager's own class wording does not relabel the security: most managers say COM
    aapl = next(p for p in body["positions"] if p["issuer"]["cik"] == "0000320193")
    assert (aapl["class_label"], aapl["title_of_class"]) == ("Common stock", "CAP STK CL A")
    assert any("thousands" in n for n in body["notes"])


def test_activity_ranks_net_managers_and_leaves_out_jumps(client, auth, db, funds):
    body = _get(client, auth, "/v1/managers/activity", quarter="2024-06-30",
                min_holders=1).json()  # fmt: skip
    rows = {r["issuer"]["cik"]: r for r in body["data"]}
    # Apple: four holders, steady shares: ranked. NVIDIA: shares x10 even after the split?
    # No: split-adjusted totals moved 1,100 x10 = 11,000 -> 10,550 (comparable): ranked.
    assert "0000320193" in rows and rows["0001045810"]["split_adjusted"] is True
    # Coca-Cola: every holder left (shares fell by more than half): left out, with a note
    assert "0000021344" not in rows and any("left out" in n for n in body["notes"])
    assert any("Coca Cola Co (no longer held)" in n for n in body["notes"]), body["notes"]
    sold = _get(client, auth, "/v1/managers/activity", quarter="2024-06-30", direction="sold",
                min_holders=1).json()["data"]  # fmt: skip
    nets = [r["net_managers"] for r in sold]
    assert nets == sorted(nets)


def test_search_errors_and_notices(client, auth, db, funds):
    found = _get(client, auth, "/v1/managers", q="alpha capital").json()["data"]
    assert [r["cik"] for r in found] == [M1] and found[0]["positions"] == 4
    assert _get(client, auth, "/v1/managers/0000999999").json()["error"]["code"] == (
        "manager_not_found")  # fmt: skip
    r = _get(client, auth, f"/v1/managers/{NT}", quarter="2024-06-30")
    nt = r.json()
    assert r.status_code == 200 and nt["notice_only"] is True and nt["positions"] == []
    assert nt["filing"]["form"] == "13F-NT"
    assert nt["filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert nt["reported_by"] == [
        {"cik": M1, "name": "ALPHA CAPITAL LLC", "files_holdings_here": True},
        {"cik": None, "name": "Elsewhere Advisers Ltd", "files_holdings_here": False}]  # fmt: skip
    bad = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-05-31")
    assert bad.status_code == 422
    assert client.get("/managers/abc/").status_code == 404


def test_demo_trims_and_showcase_scope(client, db, funds, settings, monkeypatch):
    monkeypatch.setattr(settings, "public_showcase_ciks", M1)
    body = client.get(f"/v1/managers/{M1}", params={"quarter": "2024-06-30", "limit": 50},
                      headers=DEMO).json()  # fmt: skip
    assert body["meta"]["limit"] == 10
    other = client.get(f"/v1/managers/{M2}", params={"quarter": "2024-06-30"}, headers=DEMO)
    assert other.status_code == 403


def test_the_manager_page_route_takes_digits_only(client, tmp_path, monkeypatch):
    """ui, 25 Nov: /managers/{cik} also matched /managers/manager.js and answered a JSON 404;
    the page's own files must reach the static mount; zero-padded CIKs still match."""
    from starlette.routing import Mount

    routes = client.app.routes
    pages = [r for r in routes if getattr(r, "path", "").startswith("/managers/{cik")]
    assert len(pages) == 2
    # the company page route takes digits only too: a file under /companies/ is never its CIK
    company = next(r for r in routes if getattr(r, "path", "").startswith("/companies/{cik"))
    assert company.path_regex.match("/companies/companies.js") is None
    for r in pages:
        for path in ("/managers/manager.js", "/managers/managers.css", "/managers/12345678901"):
            assert r.path_regex.match(path) is None, (r.path, path)
    m = [
        r.path_regex.match(p)
        for r in pages
        for p in ("/managers/0001067983", "/managers/0001067983/")
    ]
    assert [x.group("cik") for x in m if x] == ["0001067983", "0001067983"]
    # the static mount serves a .js and a .css under /managers/
    (tmp_path / "managers").mkdir()
    (tmp_path / "managers" / "manager.js").write_text("// page script")
    (tmp_path / "managers" / "managers.css").write_text("body{}")
    static = next(r for r in routes if isinstance(r, Mount) and r.path == "")
    monkeypatch.setattr(static.app, "directory", str(tmp_path))
    monkeypatch.setattr(static.app, "all_directories", [str(tmp_path)])
    js = client.get("/managers/manager.js")
    assert js.status_code == 200 and js.text == "// page script"
    css = client.get("/managers/managers.css")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]


def test_a_cached_view_is_never_changed_by_a_request(client, auth, db, funds):
    """The portfolio is cached per process; sorting and paging must not alter the cache."""
    a = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-06-30", sort="name").json()
    (cached,) = [v[1] for v in fm._views.values()]
    before = [x["key"] for x in cached["positions"]]
    b = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-06-30", sort="value",
             limit=1).json()  # fmt: skip
    assert [x.get("key") for x in cached["positions"]] == before  # unsorted, keys kept
    c = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-06-30", sort="name").json()
    assert a == c and len(b["positions"]) == 1 and "key" not in b["positions"][0]
    # a load bumps the holdings version: the next request reads again
    thirteenf.bump_holdings_version(db)
    db.commit()
    d = _get(client, auth, f"/v1/managers/{M1}", quarter="2024-06-30", sort="name").json()
    assert d == a


def test_a_split_adjusted_change_within_rounding_is_unchanged(client, auth, db, funds):
    """PM, 25 Nov: Ocean Power's 1:30 read as reduced by 1.27 shares; fractional shares paid in
    cash after a split are not a sale."""
    body = _get(client, auth, f"/v1/managers/{M4}", quarter="2024-06-30").json()
    nv = next(p for p in body["positions"] if p["issuer"]["cik"] == "0001045810")["change"]
    assert nv["split_adjusted"] is True and nv["status"] == "unchanged"
    assert fm.same_after_split(110_969, 110_970.2667, "1:30")
    assert not fm.same_after_split(110_000, 110_970.2667, "1:30")


def test_mcp_tools_and_chat_answers(client, auth, db, funds):
    import json

    from app.services import conversation as cv

    def tool(name, args):
        body = {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                "params": {"name": name, "arguments": args}}  # fmt: skip
        out = client.post("/mcp", json=body, headers=auth).json()
        res = out.get("result")
        assert res and res["isError"] is False, out
        return json.loads(res["content"][0]["text"])

    assert tool("search_managers", {"query": "alpha"})["data"][0]["cik"] == M1
    port = tool("manager_portfolio", {"cik": M1, "quarter": "2024-06-30"})
    assert port["manager"]["cik"] == M1 and port["positions"]
    act = tool("fund_activity", {"quarter": "2024-06-30", "min_holders": 1})
    assert act["data"] and act["labels"]["disclaimer"]
    assert cv.fund_request("Which stocks did funds buy most last quarter?")["kind"] == "activity"
    assert cv.fund_request("What are hedge funds selling?")["direction"] == "sold"
    assert cv.fund_request("What did Alpha Capital buy last quarter?") == {
        "kind": "manager", "who": "Alpha Capital", "sells": False}  # fmt: skip
    assert cv.fund_request("Who sold Apple?")["company"] == "Apple"
    for other in ("What did insiders buy?", "What did Apple report?", "Who is Apple's CEO?"):
        assert cv.fund_request(other) is None, other
    r = client.post("/v1/chat", json={"message": "What did Alpha Capital buy last quarter?"},
                    headers=auth).json()  # fmt: skip
    assert r["intent"] == "funds" and "45 days" in r["answer"]
    (table,) = [w for w in r["widgets"] if w["type"] == "table"]
    assert {row[2]["text"].split()[0] for row in table["rows"]} <= {"new", "added"}
    assert r["citations"][0]["url"].startswith("https://www.sec.gov/Archives/")
    who = client.post("/v1/chat", json={"message": "Who sold NVIDIA?"}, headers=auth).json()
    assert who["intent"] == "funds" and "split-adjusted 10:1" in who["answer"]
