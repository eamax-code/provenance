"""D-01: registrants that no longer file their own periodic reports are left out of "largest"
lists by default, stay viewable, and say when they last filed one."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.models import Company, Filing, MartCompany
from app.services import marts
from tests.integration.test_fiscal_years import _fact

LIVE, OLD, SUB = "0000000941", "0000000942", "0000000943"


def _filing(cik, n, form, filed):
    return Filing(cik=cik, accession_number=f"{cik}-26-{n:06d}", form_type=form, filing_date=filed,
                  source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/x-index.html",
                  first_detected_at=datetime.now(UTC), quality_status="ok")  # fmt: skip


def _seed(db):
    now = datetime.now(UTC)
    for cik, name in ((LIVE, "Live Corp"), (OLD, "Old Registrant Inc."),
                      (SUB, "Parent Financial Co. LLC")):  # fmt: skip
        db.add(Company(cik=cik, legal_name=name, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now,
                       quality_status="ok"))  # fmt: skip
    db.add_all([
        _filing(LIVE, 1, "10-K", date(2026, 2, 20)), _filing(LIVE, 2, "10-Q", date(2026, 10, 30)),
        _filing(OLD, 1, "10-K", date(2016, 3, 1)), _filing(OLD, 2, "8-K", date(2026, 9, 1)),
        # a debt-issuing subsidiary: only note offerings under its own CIK, the parent's figures
        _filing(SUB, 1, "424B2", date(2026, 11, 1)),
    ])  # fmt: skip
    y = (date(2025, 1, 1), date(2025, 12, 31))
    for cik, v, acc in ((LIVE, 100, f"{LIVE}-26-000001"), (OLD, 500, f"{OLD}-26-000001"),
                        (SUB, 900, "0000000999-26-000001")):  # fmt: skip
        f = _fact("revenue", v, *y, "annual", acc, "10-K", date(2026, 2, 20))
        f.cik = cik
        db.add(f)
    db.commit()
    marts.build_company_marts(db)
    marts.build_financial_marts(db)
    db.commit()


def test_only_companies_filing_their_own_reports_rank_by_default(client, auth, db):
    _seed(db)
    status = {m.cik: (m.periodic_active, m.last_periodic_form, m.last_periodic_date)
              for m in db.query(MartCompany)}  # fmt: skip
    assert status[LIVE] == (True, "10-Q", date(2026, 10, 30))
    assert status[OLD] == (False, "10-K", date(2016, 3, 1))  # an 8-K does not count
    assert status[SUB] == (False, None, None)  # a 424B2 does not count
    body = client.get("/v1/facts/screen?metric=revenue&year=2025", headers=auth).json()
    assert [r["cik"] for r in body["data"]] == [LIVE]
    assert any("include_inactive=true" in n for n in body["notes"])
    every = client.get("/v1/facts/screen?metric=revenue&year=2025&include_inactive=true",
                       headers=auth).json()  # fmt: skip
    assert [r["cik"] for r in every["data"]] == [SUB, OLD, LIVE]
    top = client.post("/v1/chat", json={"message": "largest companies by revenue"},
                      headers=auth).json()  # fmt: skip
    assert top["intent"] == "rank" and "Live Corp" in top["answer"]
    assert "Old Registrant" not in top["answer"] and "Parent Financial" not in top["answer"]


def test_an_inactive_company_stays_viewable_and_says_when_it_last_filed(client, auth, db):
    _seed(db)
    r = client.get(f"/v1/companies/{OLD}/overview", headers=auth)
    assert r.status_code == 200
    company = r.json()["company"]
    assert company["periodic_active"] is False
    assert company["last_periodic_report"] == {"form": "10-K", "filed_date": "2016-03-01"}
    assert client.get("/v1/companies/search?q=Old Registrant", headers=auth).json()["data"]


def test_screen_rows_say_whether_the_company_still_files(client, auth, db):
    _seed(db)
    body = client.get("/v1/facts/screen?metric=revenue&year=2025", headers=auth).json()
    assert [(r["cik"], r["periodic_active"]) for r in body["data"]] == [(LIVE, True)]
    every = client.get("/v1/facts/screen?metric=revenue&year=2025&include_inactive=true",
                       headers=auth).json()  # fmt: skip
    assert [(r["cik"], r["periodic_active"]) for r in every["data"]] == \
        [(SUB, False), (OLD, False), (LIVE, True)]  # fmt: skip
    # as of a date, by the filings up to it: OLD's 2016 10-K made it active then (no look-ahead)
    assert marts.periodic_status(db, {OLD, LIVE}, date(2016, 6, 1)) == {OLD: True, LIVE: False}
    assert marts.periodic_status(db, {OLD}) == {OLD: False}
