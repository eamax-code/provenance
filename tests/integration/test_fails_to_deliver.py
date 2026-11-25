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
