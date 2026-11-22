"""Filings tracker and the going-public view (ADR 0012)."""

from __future__ import annotations

import copy
from datetime import timedelta

from sqlalchemy import select

from app.db.models import Company, EdgarFeedEntry, Filing, UniverseMember, utcnow
from app.services import filings_tracker, ipo_pipeline
from app.services.ingestion import ingest_company

AAPL = "0000320193"
NEWCO = "0002999999"


def _entry(form, name, cik, role, acc, day):
    return f"""<entry>
<title>{form} - {name} ({cik}) ({role})</title>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; {day} &lt;b&gt;AccNo:&lt;/b&gt; {acc}</summary>
<updated>{day}T10:00:00-05:00</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>"""


def _hit(acc, form, cik, day):
    return {"_id": f"{acc}:doc.htm", "_source": {
        "adsh": acc, "form": form, "file_date": day, "ciks": [cik],
        "display_names": [f"Newco Robotics, Inc.  (CIK {cik})"]}}  # fmt: skip


def _feed(*entries):
    return "<feed><title>Latest Filings</title>" + "".join(entries) + "</feed>"


def _newco(submissions_aapl, filings):
    sub = copy.deepcopy(submissions_aapl)
    sub.update(cik=NEWCO, name="Newco Robotics, Inc.", tickers=[], exchanges=[], sic="3570")
    keys = list(sub["filings"]["recent"])
    sub["filings"]["recent"] = {k: [] for k in keys}
    for form, acc, day in filings:
        rec = {
            "accessionNumber": acc, "filingDate": day, "reportDate": "", "form": form,
            "acceptanceDateTime": f"{day}T14:00:00.000Z", "primaryDocument": "doc.htm",
        }  # fmt: skip
        for k in keys:
            sub["filings"]["recent"][k].append(rec.get(k, ""))
    return sub


def test_latest_feed_keeps_companies_not_reporting_people():
    day = "2026-11-19"
    text = _feed(
        _entry("S-1", "Newco Robotics, Inc.", NEWCO, "Filer", "0001-26-000001".rjust(20, "0"), day),
        _entry("4", "Apple Inc.", AAPL, "Issuer", "0001234567-26-000002", day),
        _entry("4", "COOK TIMOTHY D", "0001214156", "Reporting", "0001234567-26-000002", day),
        _entry("SCHEDULE 13G", "Apple Inc.", AAPL, "Subject", "0001234567-26-000003", day),
    )
    got = filings_tracker.parse_latest(text)
    assert [(e.form_type, e.cik, e.role) for e in got] == [
        ("S-1", NEWCO, "filer"), ("4", AAPL, "issuer"), ("SCHEDULE 13G", AAPL, "subject"),
    ]  # fmt: skip
    assert got[0].filing_date.isoformat() == day and got[0].accepted_at is not None


def test_full_text_search_hits_name_each_company():
    payload = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "adsh": "0001628280-26-074944",
                        "form": "424B4",
                        "file_date": "2026-11-19",
                        "ciks": ["0002130357"],
                        "display_names": ["Anthropic, PBC  (ANT)  (CIK 0002130357)"],
                    }
                }
            ]
        }
    }
    got = filings_tracker.parse_search(payload)  # fmt: skip
    assert [(e.cik, e.company_name, e.form_type, e.role) for e in got] == [
        ("0002130357", "Anthropic, PBC", "424B4", "filer")
    ]


def test_funds_listing_a_class_are_not_added():
    assert filings_tracker.discovers({"S-1"}, "Newco Robotics, Inc.")
    assert filings_tracker.discovers({"8-A12B", "424B4"}, "Anthropic, PBC")
    assert not filings_tracker.discovers({"8-A12B"}, "Tidal Trust IV")
    assert not filings_tracker.discovers({"8-A12B", "485BXT"}, "Wedbush Series")
    assert not filings_tracker.discovers({"8-A12B", "CERT", "497K"}, "Capital Group Income ETF")
    assert not filings_tracker.discovers({"D"}, "Anthropic Series 9 LLC")


def test_daily_index_rows_are_read():
    text = (
        "Description: Daily Index\n\nCIK|Company Name|Form Type|Date Filed|File Name\n"
        "-----\n"
        "2130357|Anthropic, PBC|424B4|20261119|edgar/data/2130357/0001628280-26-074944.txt\n"
        "2130357|Anthropic, PBC|3|20261118|edgar/data/2130357/0001033331-26-000003.txt\n"
    )
    got = filings_tracker.parse_daily_index(text)
    assert [(e.cik, e.form_type, e.accession_number, str(e.filing_date)) for e in got] == [
        ("0002130357", "424B4", "0001628280-26-074944", "2026-11-19"),
        ("0002130357", "3", "0001033331-26-000003", "2026-11-18"),
    ]


def test_tracker_refreshes_covered_companies_and_adds_one_going_public(
    db, settings, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, AAPL, include_facts=False)
    today = utcnow().date()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    s1, priced = "0009999999-26-000001", "0009999999-26-000009"
    fake_sec.add(
        f"https://data.sec.gov/submissions/CIK{NEWCO}.json",
        _newco(submissions_aapl, [("424B4", priced, d(0)), ("S-1", s1, d(20))]),
    )
    fake_sec.add(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{NEWCO}.json", {"facts": {}})
    page = _feed(
        _entry("424B4", "Newco Robotics, Inc.", NEWCO, "Filer", priced, d(0)),
        _entry("8-K", "Apple Inc.", AAPL, "Filer", "0000320193-26-000077", d(0)),
        _entry("497", "Some Fund Trust", "0000777777", "Filer", "0000777777-26-000001", d(0)),
        _entry("D", "Anthropic Series 9 LLC", "0000888888", "Filer", "0000888888-26-000001", d(0)),
    )
    fake_sec.add(filings_tracker.LATEST_URL.format(start=0), page)
    fake_sec.add(filings_tracker.LATEST_URL.format(start=100), _feed())
    east = utcnow().astimezone(filings_tracker.EASTERN).date()
    for forms, hits in ((filings_tracker.SEARCH_GOING_PUBLIC, [_hit(priced, "424B4", NEWCO, d(0))]),
                        (filings_tracker.SEARCH_REPORTS, [])):  # fmt: skip
        url = filings_tracker.SEARCH_URL.format(
            forms=",".join(forms), start=(east - timedelta(days=1)).isoformat(),
            end=east.isoformat(), offset=0,
        )  # fmt: skip
        fake_sec.add(url, {"hits": {"total": {"value": len(hits)}, "hits": hits}})

    out = filings_tracker.run_once(db, settings, sec_client, daily=False)

    assert out["search"] == {"entries": 1, "new": 1}
    assert out["latest"] == {"entries": 4, "new": 3}  # the 424B4 was already found by search
    assert (out["refreshed"], out["discovered"], out["ignored"], out["failed"]) == (1, 1, 2, 0)
    by = {e.cik: e.status for e in db.scalars(select(EdgarFeedEntry))}
    assert by == {AAPL: "refreshed", NEWCO: "discovered", "0000777777": "ignored",
                  "0000888888": "ignored"}  # fmt: skip
    assert db.get(Company, db.scalar(select(Company.id).where(Company.cik == NEWCO))) is not None
    assert db.scalar(select(UniverseMember.source).where(UniverseMember.cik == NEWCO)) == "tracker"
    # the filing the tracker saw reaches the event feed; the older history does not
    streamed = dict(db.execute(select(Filing.accession_number, Filing.stream_status)
                               .where(Filing.cik == NEWCO)).all())  # fmt: skip
    assert streamed == {priced: "published", s1: "skipped"}
    # a second read finds nothing new and stops after one page
    calls = len(fake_sec.calls)
    again = filings_tracker.run_once(db, settings, sec_client, daily=False)
    assert again["latest"]["new"] == 0 and again["companies"] == 0
    assert len(fake_sec.calls) == calls + 3  # two searches, one feed page


def test_daily_index_is_read_once_per_day_and_skips_weekends(db, settings, sec_client, fake_sec):
    from datetime import UTC, datetime

    from app.db.models import JobState

    now = datetime(2026, 11, 23, 15, 0, tzinfo=UTC)  # a Monday
    db.add(JobState(name=filings_tracker.DAILY_STATE, value="2026-11-19"))
    db.commit()
    fake_sec.add(
        filings_tracker.DAILY_URL.format(y=2026, q=4, ymd="20261120"),
        "CIK|Company Name|Form Type|Date Filed|File Name\n"
        "320193|Apple Inc.|8-K|20261120|edgar/data/320193/0000320193-26-000088.txt\n",
    )
    out = filings_tracker.read_daily_indexes(db, sec_client, now=now)
    assert out == {"days": ["2026-11-20"], "new": 1}  # Saturday and Sunday have none
    assert db.get(JobState, filings_tracker.DAILY_STATE).value == "2026-11-20"
    assert filings_tracker.read_daily_indexes(db, sec_client, now=now) == {"days": [], "new": 0}


def _company(db, cik, name):
    now = utcnow()
    db.add(Company(cik=cik, legal_name=name, source_url="https://www.sec.gov/", quality_status="ok",
                   first_detected_at=now))  # fmt: skip


def _filing(db, cik, form, day, n):
    db.add(Filing(cik=cik, accession_number=f"{cik}-26-{n:06d}", form_type=form, filing_date=day,
                  source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{n}/",
                  first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip


def test_going_public_stages_come_from_the_filings(db, client, auth):
    today = utcnow().date()
    ago = lambda n: today - timedelta(days=n)  # noqa: E731
    _company(db, "0002000001", "Priced Co")
    for i, (form, n) in enumerate([("DRS", 200), ("S-1", 40), ("S-1/A", 12), ("EFFECT", 2),
                                   ("8-A12B", 3), ("CERT", 2), ("424B4", 1)]):  # fmt: skip
        _filing(db, "0002000001", form, ago(n), i)
    _company(db, "0002000002", "Seasoned Co")  # reports already: a resale S-1 is not an IPO
    _filing(db, "0002000002", "10-K", ago(300), 1)
    _filing(db, "0002000002", "S-1", ago(10), 2)
    _company(db, "0002000003", "Pulled Co")
    _filing(db, "0002000003", "S-1", ago(50), 1)
    _filing(db, "0002000003", "RW", ago(5), 2)
    _company(db, "0002000005", "Last Year Co")  # priced a year ago, now a follow-on
    _filing(db, "0002000005", "S-1", ago(420), 1)
    _filing(db, "0002000005", "424B4", ago(380), 2)
    _filing(db, "0002000005", "S-1", ago(20), 3)
    _filing(db, "0002000005", "424B4", ago(3), 4)
    _company(db, "0002000004", "Spin Co")
    _filing(db, "0002000004", "10-12B", ago(30), 1)
    db.commit()

    rows = {r["name"]: r for r in ipo_pipeline.companies(db, ago(90))}
    assert set(rows) == {"Priced Co", "Pulled Co", "Spin Co"}
    assert rows["Priced Co"]["stage"] == "priced"
    assert set(rows["Priced Co"]["milestones"]) == set(ipo_pipeline.STAGES) - {"withdrawn"}
    assert rows["Priced Co"]["milestones"]["listing"]["form_type"] == "8-A12B"
    assert rows["Pulled Co"]["stage"] == "withdrawn"
    assert rows["Spin Co"]["kind"] == "spin_off" and rows["Spin Co"]["stage"] == "filed"

    r = client.get("/v1/ipos?stage=priced", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["name"] for x in body["data"]] == ["Priced Co"]
    assert body["data"][0]["milestones"]["priced"]["source_url"].startswith("https://www.sec.gov/")
    assert client.get("/v1/ipos?stage=rumoured", headers=auth).status_code == 400
    assert client.get("/v1/ipos?kind=spin_off", headers=auth).json()["meta"]["total_matched"] == 1


def test_poller_runs_the_tracker_once_an_hour(db, settings, monkeypatch):
    from app.jobs import filings_tracker as job

    ran = []
    monkeypatch.setattr(job, "run", lambda db, s, client=None: ran.append(1) or {})
    now = utcnow()
    assert job.maybe_run(db, settings, None, now) == now
    later = now + timedelta(minutes=30)
    assert job.maybe_run(db, settings, now, later) == now  # not yet
    hour = now + timedelta(seconds=settings.filings_tracker_interval_seconds)
    assert job.maybe_run(db, settings, now, hour) == hour
    off = settings.model_copy(update={"filings_tracker_enabled": False})
    assert job.maybe_run(db, off, None, hour) is None
    assert len(ran) == 2


def test_handled_rows_are_purged_after_a_year(db, settings):
    from app.services import retention

    now = utcnow()
    for i, (status, age) in enumerate([("refreshed", 400), ("ignored", 400), ("new", 400),
                                       ("refreshed", 30)]):  # fmt: skip
        db.add(EdgarFeedEntry(accession_number=f"0000000001-25-{i:06d}", cik=AAPL,
                              company_name="Apple Inc.", form_type="8-K", role="filer",
                              source="latest", seen_at=now - timedelta(days=age), status=status,
                              attempts=0))  # fmt: skip
    db.commit()
    assert retention.purge(db, settings, now=now)["edgar_feed"] == 2
    assert {e.status for e in db.scalars(select(EdgarFeedEntry))} == {"new", "refreshed"}
