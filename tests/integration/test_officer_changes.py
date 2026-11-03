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
