"""Officer changes read from 8-K item 5.02 text: section cutting, checks, and the chat answer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Filing, FilingSection, OfficerChange
from app.services import officer_changes as oc
from app.services.llm import LLMReply

FIX = Path(__file__).parents[1] / "fixtures"
HOFFMAN = (FIX / "8k_msft_502_hoffman.htm").read_text(encoding="utf-8")
MEETING = (FIX / "8k_msft_502_507_meeting.htm").read_text(encoding="utf-8")
EVIDENCE = (
    "On June 2, 2026, Reid Hoffman, a member of the Board of Directors of Microsoft Corporation "
    "(the “Company”) since 2017, informed the Company of his decision not to stand for "
    "re-election at the Company’s 2026 annual shareholder meeting"
)


def change(**kw):
    base = {
        "person": "Reid Hoffman",
        "role": "member of the Board of Directors",
        "change": "not_standing_for_reelection",
        "effective": "",
        "reason": "not as a result of any disagreement",
        "successor": "",
        "evidence": EVIDENCE,
    }
    return {**base, **kw}


class ExtractingLLM:
    def __init__(self, changes):
        self.changes = changes
        self.calls = 0

    def chat(self, messages, schema=None, **kw):
        self.calls += 1
        return LLMReply(
            text=json.dumps({"changes": self.changes}),
            model="fake:1b",
            duration_ms=1,
            output_tokens=10,
        )


def test_section_is_cut_between_item_heading_and_signature():
    section = oc.item_section(oc.html_to_text(HOFFMAN))
    assert section.startswith("Item 5.02") and "Reid Hoffman" in section
    assert "SIGNATURE" not in section and "/s/" not in section
    meeting = oc.item_section(oc.html_to_text(MEETING))
    assert "2026 Stock Plan" in meeting and "Deloitte" not in meeting  # stops at item 5.07


def test_verify_drops_invented_people_and_flags_unmatched_quotes():
    section = oc.item_section(oc.html_to_text(HOFFMAN))
    assert oc.verify(change(), section) == (True, True)
    assert oc.verify(change(person="Jane Invented"), section) == (False, False)
    assert oc.verify(change(evidence="Hoffman was fired for cause."), section) == (True, False)
    assert oc.verify(change(effective="2026-06-02"), section)[1] is True  # long form in text
    assert oc.verify(change(effective="2026-07-09"), section)[1] is False
    assert oc.verify(change(person="", change="departure"), section)[0] is False


def test_describe_reads_naturally():
    c = OfficerChange(
        person="Carmine Di Sibio",
        role="Board of Directors",
        change_type="appointment",
        effective="May 13, 2026",
        reason=None,
        successor=None,
    )
    assert oc.describe(c) == (
        "Carmine Di Sibio appointed to the Board of Directors, effective May 13, 2026."
    )
    c = OfficerChange(
        person="Reid Hoffman",
        role="director",
        change_type="not_standing_for_reelection",
        reason="personal reasons",
    )
    assert oc.describe(c) == (
        "Reid Hoffman, director, will not stand for re-election. Reason given: personal reasons."
    )


@pytest.fixture
def leadership_8k(db, items_aapl, fake_sec):
    f = db.scalar(select(Filing).where(Filing.items.like("%5.02%")))
    fake_sec.add(oc.document_url(f), HOFFMAN)
    return f


def _ask(client, auth, message="What are the recent leadership changes at Apple?"):
    return client.post(
        "/v1/chat", json={"message": message, "as_of": "2024-12-31"}, headers=auth
    ).json()


def test_chat_reads_the_filing_once_and_answers_with_names(
    app, client, auth, db, leadership_8k, fake_sec, sec_client
):
    llm = ExtractingLLM([change(), change(person="Jane Invented")])
    app.state.llm_factory = lambda: llm
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, auth)
    assert (
        "Reid Hoffman, member of the Board of Directors, will not stand for re-election"
        in (body["answer"])
    )
    assert "Jane Invented" not in body["answer"] and "(unverified)" not in body["answer"]
    card = body["brief"]["leadership_filings"][0]
    assert card["reading"] == "ok" and card["changes"][0]["verified"] is True
    assert body["checks"]["grounded"] is True
    doc = oc.document_url(leadership_8k)
    _ask(client, auth, "Who left the board at Apple?")
    assert fake_sec.calls.count(doc) == 1 and llm.calls == 1  # stored, not fetched again
    assert db.scalar(select(func.count(OfficerChange.id))) == 1


def test_demo_key_never_fetches_from_sec(
    app, client, db, leadership_8k, fake_sec, sec_client, settings
):
    settings.public_showcase_ciks = "320193"
    app.state.llm_factory = lambda: ExtractingLLM([change()])
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, {"X-API-Key": "demo"})
    assert oc.document_url(leadership_8k) not in fake_sec.calls
    assert "filing text not read yet" in body["answer"]
    assert db.scalar(select(func.count(FilingSection.id))) == 0


def test_filing_without_named_change_is_explained(
    app, client, auth, db, leadership_8k, fake_sec, sec_client
):
    fake_sec.add(oc.document_url(leadership_8k), MEETING)
    app.state.llm_factory = lambda: ExtractingLLM([])
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, auth)
    assert "names no individual director or officer change" in body["answer"]


def test_phrases_and_figures_are_checked_against_the_text():
    section = oc.item_section(oc.html_to_text(HOFFMAN))
    assert oc.verify(change(effective="the 2026 annual meeting"), section)[1] is True
    assert oc.verify(change(effective="the 2031 annual meeting"), section)[1] is False
    assert oc.numbers_in_text("director since 2017", section)
    assert not oc.numbers_in_text("granted 96,000,000 shares", section)


def test_named_pay_change_is_described_with_its_terms():
    c = OfficerChange(
        person="Elon Musk",
        role="Chief Executive Officer",
        change_type="compensation",
        what="granted 96,000,000 restricted shares as an interim award",
    )
    assert oc.describe(c) == (
        "Elon Musk, Chief Executive Officer: granted 96,000,000 restricted shares as an interim "
        "award."
    )


def test_shortened_quote_is_traced_to_the_filing_sentence():
    section = oc.item_section(oc.html_to_text(HOFFMAN))
    short = (
        "Mr. Hoffman informed the Company of his decision not to stand for re-election at the "
        "Company\u2019s 2026 annual shareholder meeting"
    )
    original = oc.source_sentence(short, section)
    assert original.startswith("(b) On June 2, 2026, Reid Hoffman, a member of the Board")
    assert oc.verify(change(evidence=short), section) == (True, True)
    assert (
        oc.source_sentence("Mr. Hoffman informed the Company in 2019 of his plans", section) is None
    )


def test_appointee_shows_who_they_replace():
    c = OfficerChange(
        person="Sabih Khan",
        role="Chief Operating Officer",
        change_type="appointment",
        effective="July 25, 2025",
        successor="Jeff Williams",
    )
    assert oc.describe(c).endswith("effective July 25, 2025. Replaces: Jeff Williams.")


def test_changes_read_from_now_on_are_published_on_the_feed(
    client, auth, db, settings, leadership_8k, sec_client
):
    from datetime import UTC, datetime, timedelta

    settings.events_settle_seconds = 0
    old = OfficerChange(
        cik=leadership_8k.cik, accession_number="0000000000-20-000001", seq=0,
        change_type="departed", source_url="https://www.sec.gov/x", verified=True,
        extractor_version="1.0.0", stream_status="published", stream_at=None,
    )  # fmt: skip
    db.add(old)
    db.commit()
    oc.ensure_extracted(db, [leadership_8k], sec=sec_client, llm=ExtractingLLM([change()]))
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    body = client.get(f"/v1/events?types=leadership&since={since}", headers=auth).json()
    assert len(body["data"]) == 1  # the one read now; the older reading never streams
    event = body["data"][0]
    assert event["type"] == "sec.officer_change" and event["kind"] == "leadership"
    data = event["data"]
    assert data["person"] == "Reid Hoffman" and data["verified"] is True
    assert "On June 2, 2026, Reid Hoffman" in data["evidence"]  # the filing sentence
    assert data["source_url"].startswith("https://www.sec.gov/Archives/")
    assert data["company_name"] and data["accession_number"] == leadership_8k.accession_number
    by_cik = client.get(f"/v1/events?cik=320193&since={since}", headers=auth).json()["data"]
    assert "leadership" in {e["kind"] for e in by_cik}


def test_latest_8k_feed_is_parsed():
    from app.jobs.current_8k import parse_feed

    entries = parse_feed((FIX / "edgar_current_8k.atom").read_text(encoding="utf-8"))
    assert len(entries) == 4
    by_cik = {e.cik: e for e in entries}
    algo = by_cik["0000923601"]
    assert algo.company == "Algorhythm Holdings, Inc." and algo.form == "8-K"
    assert algo.items == ("5.02", "8.01", "9.01") and algo.updated is not None
    assert sum("5.02" in e.items for e in entries) == 2


def test_latest_8k_poll_reads_new_502_filings_once(
    client, auth, db, settings, leadership_8k, sec_client, fake_sec
):
    from datetime import UTC, datetime, timedelta

    from app.jobs import current_8k

    settings.events_settle_seconds = 0
    feed = (FIX / "edgar_current_8k.atom").read_text(encoding="utf-8")
    # Point Datavault's 5.02 entry at the Apple 8-K whose document the fixtures hold.
    feed = feed.replace("(0001682149)", "(0000320193)").replace(
        next(e.accession_number for e in current_8k.parse_feed(feed) if e.cik == "0001682149"),
        leadership_8k.accession_number,
    )
    fake_sec.add(current_8k.FEED_URL, feed)
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000923601.json", {"cik": "923601"}, status=404
    )
    llm = ExtractingLLM([change()])
    summary = current_8k.run_once(db, settings, sec_client, llm)
    assert summary["entries"] == 4 and summary["with_502"] == 2
    assert summary["read"] == 1 and summary["extracted"] == 1 and llm.calls == 1
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    events = client.get(f"/v1/events?types=leadership&since={since}", headers=auth).json()
    assert [e["data"]["person"] for e in events["data"]] == ["Reid Hoffman"]
    again = current_8k.run_once(db, settings, sec_client, llm)
    assert again["read"] == 0 and llm.calls == 1  # read once


def test_context_uses_only_figures_filed_by_the_change(db, items_aapl):
    from datetime import date

    from app.services import marts
    from app.services.leadership_context import context_for

    marts.build_financial_marts(db)

    def officer(change_type, filed, person="Jeff Williams", seq=0):
        c = OfficerChange(
            cik="0000320193", accession_number=f"0000320193-{filed.year % 100}-{seq:06d}", seq=seq,
            filing_date=filed, person=person, change_type=change_type, verified=True,
            source_url="https://www.sec.gov/x", extractor_version="t",
        )  # fmt: skip
        db.add(c)
        db.flush()
        return c

    late = officer("departure", date(2024, 12, 31))
    ctx = context_for(db, late)
    window = ctx["before_change"]
    assert window["fiscal_years"] == [2023, 2024] and window["revenue_growth_per_year_pct"] < 5
    assert all(u.startswith("https://www.sec.gov/") for u in window["sources"])
    assert ctx["peers"] is None  # fewer than five SIC peers in the fixtures
    # Before the FY2024 10-K was filed (2024-11-01) only fiscal 2023 is known: no window yet.
    early = officer("departure", date(2024, 10, 1), seq=1)
    assert context_for(db, early)["before_change"] is None
    # A recorded appointment of the same person gives a tenure window.
    officer("appointment", date(2022, 1, 15), person="Jeffrey E. Williams", seq=2)
    tenure = context_for(db, late)["tenure"]
    assert tenure["appointed_filing_date"] == "2022-01-15" and tenure["fiscal_years"][1] == 2024
