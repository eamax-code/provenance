"""Q-06: the SEC's fails-to-deliver per company (docs/contracts/fails-to-deliver.md)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.models import Company, FailsToDeliver, FtdFile, IssuerCusip
from app.services import fails_to_deliver as ftd

CIK = "0000000930"
A, C, OTHER = "12345A101", "12345A309", "99999Z109"  # class A, class C, another issuer


def _zip(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cnsfails202610a", "\n".join(lines))
    return buf.getvalue()


def test_parse_reads_the_layout_and_a_dot_price_is_null():
    data = _zip(["SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE",
                 f"20261001|{A}|ABCD|182345|ABCD CORP CL A|12.41",
                 f"20261002|{C}|ABCDC|500|ABCD CORP\x00 CL C|.",  # a stray NUL (2015 files)
                 "Trailer text"])  # fmt: skip
    rows = ftd.parse(data)
    assert rows[1]["description"] == "ABCD CORP CL C"
    assert [(r["settlement_date"], r["quantity"], r["price"]) for r in rows] == [
        (date(2026, 10, 1), 182345, Decimal("12.41")), (date(2026, 10, 2), 500, None)]  # fmt: skip
    assert ftd.discover('<a href="/files/data/fails-deliver-data/cnsfails202610b.zip">x</a>'
                        '<a href="/files/x/cnsfails200906b.zip">old</a>') == {
        "cnsfails202610b.zip": "https://www.sec.gov/files/data/fails-deliver-data/"
                               "cnsfails202610b.zip"}  # fmt: skip


def _seed(db):
    now = datetime.now(UTC)
    db.add(Company(cik=CIK, legal_name="ABCD CORP", ticker="ABCD", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now, quality_status="ok"))  # fmt: skip
    db.add_all([IssuerCusip(cusip=A, cik=CIK, class_title="Class A common stock", method="isin"),
                IssuerCusip(cusip=C, cik=CIK, class_title="Class C capital stock",
                            method="issuer_prefix")])  # fmt: skip
    db.commit()
    rows = [{"settlement_date": date(2026, 10, 1), "cusip": A, "symbol": "ABCD", "quantity": 182345,
             "description": "ABCD CORP CL A", "price": Decimal("12.41")},
            {"settlement_date": date(2026, 10, 2), "cusip": C, "symbol": "ABCDC", "quantity": 500,
             "description": "ABCD CORP CL C", "price": None},
            {"settlement_date": date(2026, 10, 2), "cusip": OTHER, "symbol": "ZZZ",
             "quantity": 9, "description": "OTHER", "price": Decimal("1")}]  # fmt: skip
    got = ftd.store(db, "cnsfails202610a.zip", rows, date(2026, 10, 31))
    db.commit()
    assert got["matched"] == 2 and got["unmatched_cusips"] == 1
    late = [{"settlement_date": date(2026, 10, 20), "cusip": A, "symbol": "ABCD",
             "quantity": 7000, "description": "ABCD CORP CL A",
             "price": Decimal("13")}]  # fmt: skip
    ftd.store(db, "cnsfails202610b.zip", late, date(2026, 11, 14))
    db.commit()


def test_one_table_per_class_never_a_cusip_and_as_of_on_publication(client, auth, db):
    _seed(db)
    r = client.get(f"/v1/companies/{CIK}/fails-to-deliver?since=2026-09-01&until=2026-10-31",
                   headers=auth)  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    text = json.dumps(body)
    assert A not in text and C not in text and OTHER not in text and "cusip" not in text.lower()
    by = {g["symbol"]: g for g in body["data"]}
    assert set(by) == {"ABCD", "ABCDC"}  # the other issuer's row is absent, not zero
    a = by["ABCD"]
    assert a["class_label"] == "Class A common stock"
    assert [x["quantity"] for x in a["rows"]] == [182345, 7000]
    assert a["rows"][0]["value"] == {"value": 2262901.45, "derived": True,
                                     "basis": "quantity x price"}  # fmt: skip
    assert a["rows"][0]["source"] == {"file": "cnsfails202610a.zip", "published": "2026-10-31"}
    c = by["ABCDC"]["rows"][0]
    assert c["price"] is None and c["value"] is None
    assert any("running balance" in n for n in body["notes"])
    early = client.get(f"/v1/companies/{CIK}/fails-to-deliver?since=2026-09-01&until=2026-10-31"
                       "&as_of=2026-11-01", headers=auth).json()  # fmt: skip
    assert [x["quantity"] for x in {g["symbol"]: g for g in early["data"]}["ABCD"]["rows"]] == [
        182345]  # the second half's file was not yet published  # fmt: skip
    assert early["coverage"]["latest_file"] == "cnsfails202610a.zip"
    assert db.query(FailsToDeliver).count() == 3 and db.query(FtdFile).count() == 2


def test_unknown_company_is_404(client, auth):
    r = client.get("/v1/companies/0000000931/fails-to-deliver", headers=auth)
    assert r.status_code == 404


def test_the_daily_load_takes_new_files_once(db, tmp_path):
    """Q-06: the daily connections job loads the files published since its last run, each once
    (idempotent: a second run finds nothing to load)."""
    from types import SimpleNamespace

    now = datetime.now(UTC)
    db.add(Company(cik=CIK, legal_name="ABCD CORP", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now, quality_status="ok"))  # fmt: skip
    db.add(IssuerCusip(cusip=A, cik=CIK, class_title=None, method="isin"))
    db.commit()
    page = '<a href="/files/data/fails-deliver-data/cnsfails202610a.zip">October</a>'
    body = _zip(["SETTLEMENT DATE|CUSIP|SYMBOL|QUANTITY (FAILS)|DESCRIPTION|PRICE",
                 f"20261001|{A}|ABCD|100|ABCD CORP|5.00"])  # fmt: skip

    class Sec:
        fetched = 0

        def get_text(self, url):
            return SimpleNamespace(data=page)

        def download_file(self, url, dest):
            Sec.fetched += 1
            dest.write_bytes(body)
            return {"path": str(dest), "last_modified": datetime(2026, 10, 31, tzinfo=UTC)}

    first = ftd.load_new(db, Sec(), tmp_path)
    again = ftd.load_new(db, Sec(), tmp_path)
    assert (first["files_to_load"], first["matched"], again["files_to_load"]) == (1, 1, 0)
    assert Sec.fetched == 1
    assert db.get(FtdFile, "cnsfails202610a.zip").published == date(2026, 10, 31)


BANNED = ("short squeeze", "squeeze", "naked short", "naked")
SEC_SENTENCE = ("are not evidence of abusive short selling or \\u201cnaked\\u201d short "
                "selling")


def test_mcp_and_chat_quote_the_running_balance_and_never_squeeze_or_naked(client, auth, db):
    """Q-06: the MCP tool carries the labels; chat answers only "fails to deliver for X", quotes
    the running-balance label every time and never says "short squeeze" or "naked short"."""
    _seed(db)
    tools = {t["name"]: t for t in client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=auth).json()["result"]["tools"]}  # fmt: skip
    desc = tools["company_fails_to_deliver"]["description"].lower()
    assert "running balance" in desc and not any(w in desc for w in BANNED)
    rpc = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "company_fails_to_deliver",
        "arguments": {"cik": CIK, "since": "2026-09-01", "until": "2026-10-31"}}}  # fmt: skip
    res = client.post("/mcp", json=rpc, headers=auth).json()["result"]
    assert res["isError"] is False and A not in res["content"][0]["text"]
    for message in ("fails to deliver for ABCD", "What are the fails-to-deliver?"):
        one = client.post("/v1/chat", json={"message": message, "cik": CIK},
                          headers=auth).json()  # fmt: skip
        assert one["intent"] == "fails_to_deliver", one
        # only the SEC's own sentence, quoted, may name naked short selling (PM): it is removed
        # before the check; anything else is forbidden
        raw = json.dumps(one).lower().replace(SEC_SENTENCE.lower(), "")
        assert "running balance, not the day's new fails" in one["answer"]
        assert not any(w in raw for w in BANNED), [w for w in BANNED if w in raw]
        assert A not in raw and "cusip" not in raw.replace("no cusip of this company", "")
    empty = client.post("/v1/chat", json={"message": "fails to deliver", "cik": "0000000930"},
                        headers=auth).json()  # fmt: skip
    assert "running balance" in empty["answer"]
