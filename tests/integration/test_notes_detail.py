"""N-01: notes_detail beside notes, the same notes in order, each for readers or developers."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.models import Company, DividendFact
from app.services import notes as N
from tests.integration import test_fails_to_deliver as ftd_t
from tests.integration import test_periodic_active as pa_t
from tests.integration import test_sections as sec_t
from tests.integration.test_dividends import _fact
from tests.integration.test_insider_screener import trades  # noqa: F401 (fixture)
from tests.integration.test_managers import funds  # noqa: F401 (fixture)


def _check(body: dict, developer: list[str] = ()) -> dict[str, str]:
    """notes_detail is notes, in order, with an audience; the developer notes are those named."""
    got = body["notes_detail"]
    assert [d["text"] for d in got] == body["notes"]
    assert {d["audience"] for d in got} <= {"reader", "developer"}
    who = {d["text"]: d["audience"] for d in got}
    for start in developer:
        assert [a for t, a in who.items() if t.startswith(start)] == ["developer"], start
    return who


def test_detail_keeps_order_and_text():
    notes = ["For readers.", N.dev("field is null on every row."), "Also for readers."]
    assert N.detail(notes) == [
        {"text": "For readers.", "audience": "reader"},
        {"text": "field is null on every row.", "audience": "developer"},
        {"text": "Also for readers.", "audience": "reader"},
    ]
    assert N.with_detail({"x": 1})["notes_detail"] == []


def test_dividends_split_reader_and_field_notes(client, auth, db):
    cik, now = "0000000909", datetime.now(UTC)
    db.add(Company(cik=cik, legal_name="NOTES CO", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now, quality_status="ok"))  # fmt: skip
    y = (date(2025, 1, 1), date(2025, 12, 31))
    db.add(_fact(DividendFact, cik, "dividends_per_share", 1.0, "USD/shares", *y, "annual",
                 "0000000909-26-000001", date(2026, 2, 1)))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{cik}/dividends", headers=auth).json()
    who = _check(body, developer=["split_adjusted puts", "special is not given yet"])
    assert who["As reported: each value in the share basis of the filing it cites. "
               "No yield: prices are not loaded."] == "reader"  # fmt: skip


def test_ftd_and_screen(client, auth, db):
    ftd_t._seed(db)
    body = client.get(f"/v1/companies/{ftd_t.CIK}/fails-to-deliver?since=2026-09-01"
                      "&until=2026-10-31", headers=auth).json()  # fmt: skip
    who = _check(body, developer=["price: the previous day's close"])
    assert who["Information, not signals. Not investment advice."] == "reader"
    pa_t._seed(db)
    body = client.get("/v1/facts/screen?metric=revenue&year=2025", headers=auth).json()
    who = _check(body, developer=["One row per company", "Fiscal years differ", "Only companies"])
    assert [a for t, a in who.items() if "include_inactive=true" in t] == ["reader"]


def test_insider_screener(client, auth, db, trades):  # noqa: F811
    body = client.get("/v1/insider-transactions", params={"since": "2026-10-25",
                      "until": "2026-11-24"}, headers=auth).json()  # fmt: skip
    _check(body, developer=["Amendments (Form 4/A) never make a row"])


def test_managers(client, auth, db, funds):  # noqa: F811
    body = client.get("/v1/managers/activity", params={"quarter": "2024-06-30",
                      "min_holders": 1}, headers=auth).json()  # fmt: skip
    assert body["notes"] and set(_check(body).values()) == {"reader"}


def test_sections(client, auth, db):
    sec_t._seed(db)
    body = client.get(f"/v1/filings/{sec_t.ACC}/sections/1A", headers=auth).json()
    assert _check(body) == {"Text as filed, from the document linked; never summarised.": "reader"}
