"""Registration statements (S-1/F-1) read as text for companies going public."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.api.routes_chat import add_missing_citations
from app.db.models import Company, Filing, FilingSection
from app.services import intel
from app.services import prospectus as pr
from app.services.llm import LLMReply

S1 = (Path(__file__).parents[1] / "fixtures" / "s1_example.htm").read_text(encoding="utf-8")
CIK = "0002999001"


class FakeLLM:
    def __init__(self, text="Revenue was $26,045 thousand in the nine months [3]."):
        self.text = text
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return LLMReply(text=self.text, model="fake:1b", duration_ms=1, output_tokens=10)


def test_sections_are_cut_by_the_table_of_contents():
    s = pr.split_sections(S1)
    assert {"pr:summ", "pr:risk", "pr:use", "pr:mgmt", "pr:owner"} <= set(s)
    assert s["pr:risk"].startswith("Risk Factors") and "forward-looking" not in s["pr:risk"]
    assert "Table of Contents" not in s["pr:summ"]  # page furniture is dropped
    assert "Priya Raman | 44 | Chief Executive Officer and Director" in s["pr:mgmt"]
    assert "Priya Raman | 14,250,000 | 21.4%" in s["pr:owner"]


def test_sections_fall_back_to_heading_lines_without_links():
    s = pr.split_sections(re.sub(r'href="#[^"]+"', "", S1))
    assert "two cloud providers" in s["pr:risk"] and "$84.2 million" in s["pr:use"]


def test_key_figures_name_each_period():
    figures = pr.key_figures(pr.split_sections(S1))
    assert "Amounts in thousands." in figures
    assert (
        "Revenue: Year Ended December 31, 2023: $12,400; Year Ended December 31, 2024: $18,950; "
        "Year Ended December 31, 2025: $27,310; Nine Months Ended September 30, 2025: $19,880; "
        "Nine Months Ended September 30, 2026: $26,045"
    ) in figures
    assert "Nine Months Ended September 30, 2026: $(1,105)" in figures


def test_passages_follow_the_question():
    s = pr.split_sections(S1)
    risks = pr.passages(s, "What are the main risks?")
    assert risks[0][0] == "pr:risk" and risks[0][1].startswith("Risk Factors Summary")
    ceo = pr.passages(s, "Who is the CEO?")
    assert ceo[0][0] == "pr:mgmt" and "Priya Raman | 44" in ceo[0][1]
    money = pr.passages(s, "How much will the IPO raise and what is the money for?")
    assert money[0][0] == "pr:use" and "$84.2 million" in money[0][1]


@pytest.fixture
def going_public(db, items_aapl, fake_sec):
    """A company with no annual reports yet and an S-1 on file."""
    now = datetime.now(UTC)
    db.add(
        Company(
            cik=CIK,
            legal_name="Lumen Example Labs, Inc.",
            source_url=f"https://data.sec.gov/submissions/CIK{CIK}.json",
            first_detected_at=now,
        )
    )
    db.flush()
    f = Filing(
        cik=CIK,
        accession_number="0002999001-26-000002",
        form_type="S-1",
        filing_date=date(2026, 10, 20),
        primary_document="lumen-s1.htm",
        source_url="https://www.sec.gov/Archives/edgar/data/2999001/000299900126000002/"
        "0002999001-26-000002-index.html",
        first_detected_at=now,
        quality_status="ok",
    )
    db.add(f)
    db.commit()
    fake_sec.add(pr.document_url(f), S1)
    return f


def _ask(client, headers, message="What are the main risks for Lumen Example Labs?"):
    r = client.post("/v1/chat", json={"message": message}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_chat_reads_the_prospectus_once_and_cites_it(
    app, client, auth, db, going_public, fake_sec, sec_client
):
    llm = FakeLLM("They depend on two cloud providers for all computing capacity [4].")
    app.state.llm_factory = lambda: llm
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, auth)
    assert body["company"]["cik"] == CIK and body["answered_by"] == "model"
    context = llm.calls[0][1]["content"]
    assert "From S-1 filed 2026-10-20, Risk factors: Risk Factors Summary" in context
    assert "Nine Months Ended September 30, 2026: $26,045" in context  # key figures
    assert "route-planning software" in context  # the overview, not the preamble
    labels = [c["label"] for c in body["citations"]]
    assert "S-1 filed 2026-10-20, Risk factors" in labels
    assert body["brief"]["coverage"]["prospectus"]["form_type"] == "S-1"
    doc = pr.document_url(going_public)
    _ask(client, auth, "Who is the CEO of Lumen Example Labs?")
    assert fake_sec.calls.count(doc) == 1  # stored, not fetched again


def test_demo_key_answers_any_company_but_never_fetches(
    app, client, db, going_public, fake_sec, sec_client, settings
):
    settings.public_showcase_ciks = "320193"
    llm = FakeLLM("The filings list an S-1 filed 2026-10-20 [2].")
    app.state.llm_factory = lambda: llm
    app.state.sec_client_factory = lambda: sec_client
    demo = {"X-API-Key": "demo"}
    body = _ask(client, demo)  # outside the showcase list, still answered
    assert body["company"]["cik"] == CIK
    assert pr.document_url(going_public) not in fake_sec.calls
    assert "its text has not been read in this service yet" in llm.calls[0][1]["content"]
    assert db.scalar(select(func.count(FilingSection.id))) == 0
    pr.ensure_read(db, going_public, sec_client)  # read ahead of time, as the script does
    _ask(client, demo)
    assert "Risk Factors Summary" in llm.calls[1][1]["content"]


def test_leadership_question_without_8ks_uses_the_prospectus(
    app, client, auth, db, going_public, sec_client
):
    llm = FakeLLM("Priya Raman is the Chief Executive Officer [4].")
    app.state.llm_factory = lambda: llm
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, auth, "Who is the CEO of Lumen Example Labs?")
    assert body["intent"] == "question" and "Priya Raman | 44" in llm.calls[0][1]["content"]


def test_growth_question_without_annual_figures_uses_the_prospectus(
    app, client, auth, db, going_public, sec_client
):
    llm = FakeLLM()
    app.state.llm_factory = lambda: llm
    app.state.sec_client_factory = lambda: sec_client
    body = _ask(client, auth, "How has Lumen Example Labs revenue grown?")
    assert body["answered_by"] == "model" and llm.calls


def test_question_words_do_not_pick_other_companies(db, going_public):
    now = datetime.now(UTC)
    for cik, name, ticker in [
        ("0002999002", "Main Street Capital CORP", "MAIN"),
        ("0002999003", "iPower Inc.", "IPW"),
        ("0002999004", "Grown Rogue International Inc.", "GRUSF"),
        ("0002999005", "C3.ai, Inc.", "AI"),
        ("0002999006", "Anthropic, PBC", None),
    ]:
        db.add(
            Company(
                cik=cik,
                legal_name=name,
                ticker=ticker,
                source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                first_detected_at=now,
            )
        )
    db.commit()
    for q in [
        "What are the main risks for Anthropic?",
        "How much is Anthropic raising in its IPO?",
        "How has Anthropic's revenue grown?",
        "What AI risks does Anthropic list?",
    ]:
        assert intel.resolve_company(db, q).cik == "0002999006", q
    assert intel.resolve_company(db, "MAIN dividend").cik == "0002999002"


def test_added_citations_keep_line_breaks():
    answer, _ = add_missing_citations(
        "Risks include:\n- Outages.\n- Losses.", ["[2] Outages and losses."]
    )
    assert answer == "Risks include:\n- Outages.\n- Losses."
