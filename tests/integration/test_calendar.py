"""X-15 calendars (docs/contracts/calendar.md)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from app.db.models import Company, Filing
from app.services import company_calendar as cal

CIK = "0000320193"


def test_business_days_and_categories():
    assert cal.next_business_day(date(2026, 11, 26)) == date(2026, 11, 27)  # Thanksgiving
    assert cal.next_business_day(date(2026, 12, 25)) == date(2026, 12, 28)  # Fri holiday, weekend
    assert cal.next_business_day(date(2027, 1, 16)) == date(2027, 1, 19)  # Sat, then MLK Day
    assert cal.category("Large accelerated filer") == "large"
    assert cal.category("Non-accelerated filer; Smaller reporting company") == "other"
    assert cal.category("Accelerated filer") == "accelerated"
    assert cal.category("Emerging growth company") is None  # does not say: no deadline


def _f(db, acc, form, filed, period=None):
    db.add(Filing(cik=CIK, accession_number=acc, form_type=form, filing_date=filed,
                  report_date=period,
                  source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc}-index.html",
                  first_detected_at=datetime.now(UTC), quality_status="ok"))  # fmt: skip


def _seed(db):
    c = db.scalar(select(Company).where(Company.cik == CIK))
    c.filer_category = "Large accelerated filer"
    _f(db, "0000320193-25-900001", "10-K", date(2025, 10, 31), date(2025, 9, 27))
    _f(db, "0000320193-26-900002", "10-Q", date(2026, 1, 30), date(2025, 12, 27))
    _f(db, "0000320193-26-900003", "10-Q", date(2026, 5, 15), date(2026, 3, 28))  # late
    _f(db, "0000320193-26-900004", "NT 10-Q", date(2026, 5, 8))
    db.commit()


def test_company_calendar(client, auth, db, ingested_aapl):
    _seed(db)
    r = client.get(f"/v1/companies/{CIK}/calendar?from=2026-01-01&to=2026-12-31", headers=auth)
    assert r.status_code == 200
    body = r.json()
    deadlines = {i["period_end"]: i for i in body["data"] if i["kind"] == "filing_deadline"}
    q1 = deadlines["2025-12-27"]
    assert q1["date"] == "2026-02-05" and q1["derived"] is True and "40 days" in q1["basis"]
    assert q1["met_by"]["accession_number"] == "0000320193-26-900002" and not q1["filed_late"]
    assert deadlines["2026-03-28"]["filed_late"] is True
    # projected: the next quarters and the annual report, not filed yet
    assert deadlines["2026-09-28"]["title"].startswith("10-K due")
    assert (
        deadlines["2026-09-28"]["met_by"] is None and "60 days" in deadlines["2026-09-28"]["basis"]
    )
    late = [i for i in body["data"] if i["kind"] == "late_notice"]
    assert late and late[0]["derived"] is False and late[0]["date"] == "2026-05-08"
    assert all(i["source"]["source_url"].startswith("https://www.sec.gov/Archives/")
               for i in body["data"])  # fmt: skip
    only = client.get(f"/v1/companies/{CIK}/calendar?from=2026-01-01&to=2026-12-31"
                      "&kinds=late_notice", headers=auth).json()  # fmt: skip
    assert {i["kind"] for i in only["data"]} == {"late_notice"}


def test_calendar_parameters_and_lists(client, auth, db, ingested_aapl):
    _seed(db)
    too_long = client.get(f"/v1/companies/{CIK}/calendar?from=2026-01-01&to=2027-06-01",
                          headers=auth)  # fmt: skip
    assert too_long.status_code == 422
    assert client.get(f"/v1/companies/{CIK}/calendar?kinds=nope", headers=auth).status_code == 422
    many = client.get(f"/v1/calendar?ciks={CIK},789019&from=2026-01-01&to=2026-12-31",
                      headers=auth)  # fmt: skip
    assert many.status_code == 200 and many.json()["meta"]["truncated"] is False
    assert any(i["company"]["cik"] == CIK for i in many.json()["data"])
    w = client.post("/v1/watchlists", headers=auth, json={"name": "cal", "ciks": [CIK]}).json()
    wl = client.get(f"/v1/watchlists/{w['id']}/calendar?from=2026-01-01&to=2026-12-31",
                    headers=auth)  # fmt: skip
    assert wl.status_code == 200 and wl.json()["data"]
    assert client.get("/v1/watchlists/wl_00000000000000000000000000000000/calendar",
                      headers=auth).status_code == 404  # fmt: skip


def test_calendar_chat_answer(client, auth, db, ingested_aapl):
    _seed(db)
    from app.services.chat_intents import detect

    assert detect("When is Apple's next 10-K due?") == "calendar"
    assert detect("Did JPMorgan file late?") == "calendar"
    body = client.post("/v1/chat", json={"message": "Did Apple file late?", "cik": CIK},
                       headers=auth).json()  # fmt: skip
    assert body["intent"] == "calendar" and body["answered_by"] == "data"
    a = body["answer"]
    assert "derived: Large accelerated filer" in a
    assert "Filed after the derived due date in the last two years: 2026-03-28" in a
    assert "NT 10-Q on 2026-05-08" in a and "[" in a


def test_calendar_chat_answers_the_deadline_asked_about(client, auth, db, ingested_aapl):
    """2026-11-24 (provenance-ui): "When is Apple Inc.'s 10-K due (period ending 2026-09-26)
    (2026-11-25)?" was answered with the next 10-K, a year later. A deadline named by its due date
    or period end is answered itself, met or not."""
    _seed(db)

    def ask(q):
        body = client.post("/v1/chat", json={"message": q, "cik": CIK}, headers=auth).json()
        assert body["intent"] == "calendar", body
        return body["answer"]

    a = ask("When is Apple Inc.'s 10-Q due (period ending 2025-12-27) (2026-02-05), and how is "
            "that date worked out?")  # fmt: skip
    assert a.startswith("Apple Inc.'s 10-Q for the period ending 2025-12-27 was due 2026-02-05 "
                        "(derived: Large accelerated filer: 40 days")  # fmt: skip
    assert "It was filed " in a and "by the due date" in a and "next" not in a
    b = ask("When is Apple Inc.'s 10-K due (period ending 2026-09-28)?")
    assert b.startswith("Apple Inc.'s 10-K for the period ending 2026-09-28 is due ")
    assert "has not been filed yet" in b
