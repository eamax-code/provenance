"""C-07: the chat accuracy eval. 60 questions over the test fixtures, answered without a model
(the deployed default), scored on exact figures, empty answers and uncited figures.

Gates: every case outside KNOWN_FAILURES passes; no reply states a money figure in a sentence
without a citation to a filing (sec.gov/Archives); exact-figure accuracy (figure and ratio
cases) at least 95% once KNOWN_FAILURES holds no figure case. A known failure that starts passing
fails the test too, so the list only shrinks. c06 cases are intents that land with C-06.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.api import routes_chat
from app.api.routes_chat import get_llm
from app.db.models import Company, Filing, FinancialFact
from app.services import marts
from app.services.intel import money

CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "chat_eval" / "questions.json").read_text()
)["cases"]
FIGURE_KINDS = ("figure", "ratio")

# id -> why it fails today; each fix removes its entry (C-07, 2026-11-23)
KNOWN_FAILURES: dict[str, str] = {}

MONEY = re.compile(r"(?:\$|\b[A-Z]{3} )-?[\d,]+(?:\.\d+)? (?:trillion|billion|million)\b")
CITE = re.compile(r"\[(\d+)\]")


class NoModel:
    def chat(self, messages, **kw):
        from app.services.llm import LLMUnavailable

        raise LLMUnavailable("No model in the eval: the deployed default.")


def _filing(cik: str, n: int, form: str, filed: date) -> Filing:
    acc = f"{cik}-{filed:%y}-{n:06d}"
    return Filing(
        cik=cik, accession_number=acc, form_type=form, filing_date=filed,
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
        f"{acc}-index.html",
        first_detected_at=datetime.now(UTC), quality_status="ok",
    )  # fmt: skip


def _fact(f: Filing, metric: str, value: float, unit: str, start: date | None, end: date,
          tag: str, taxonomy: str) -> FinancialFact:  # fmt: skip
    now = datetime.now(UTC)
    key = hashlib.sha256(f"{f.cik}|{metric}|{end}|{f.accession_number}".encode()).hexdigest()
    return FinancialFact(
        cik=f.cik, metric=metric, value=value, unit=unit, currency=unit, period_start=start,
        period_end=end, period_type="duration" if start else "instant", period_class="annual",
        fiscal_year=end.year, fiscal_period="FY", form_type=f.form_type, filed_date=f.filing_date,
        accession_number=f.accession_number, source_tag=tag, source_taxonomy=taxonomy,
        source_url=f.source_url, mapping_version="1.5.0", quality_status="ok", derived=False,
        observation_key=key, first_detected_at=now, processed_at=now,
    )  # fmt: skip


def _company(db, cik: str, name: str, ticker: str | None, sic: str = "3570") -> None:
    now = datetime.now(UTC)
    db.add(Company(cik=cik, legal_name=name, ticker=ticker, sic_code=sic,
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip


@pytest.fixture
def eval_db(db, items_aapl, sec_client):
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "789019")
    # a second US filer (calendar years) and an IFRS filer reporting in euros: test data only
    _company(db, "0009100002", "Northwind Example Corp", "NWEX")
    _company(db, "0009100001", "Exemplar Industrie SE", "EXIN")
    db.flush()
    nw23, nw24 = (
        _filing("0009100002", 1, "10-K", date(2024, 2, 15)),
        _filing("0009100002", 2, "10-K", date(2025, 2, 14)),
    )
    ex23, ex24 = (
        _filing("0009100001", 1, "20-F", date(2024, 3, 20)),
        _filing("0009100001", 2, "20-F", date(2025, 3, 19)),
    )
    db.add_all([nw23, nw24, ex23, ex24])
    y23, y24 = (date(2023, 1, 1), date(2023, 12, 31)), (date(2024, 1, 1), date(2024, 12, 31))
    rows = [
        (nw23, "revenue", 46e9, *y23, "Revenues"),
        (nw24, "revenue", 50e9, *y24, "Revenues"),
        (nw23, "operating_income", 6e9, *y23, "OperatingIncomeLoss"),
        (nw24, "operating_income", 7.5e9, *y24, "OperatingIncomeLoss"),
        (nw23, "net_income", 4.2e9, *y23, "NetIncomeLoss"),
        (nw24, "net_income", 5e9, *y24, "NetIncomeLoss"),
        (nw24, "total_assets", 80e9, None, y24[1], "Assets"),
    ]
    for f, metric, v, start, end, tag in rows:
        db.add(_fact(f, metric, v, "USD", start, end, tag, "us-gaap"))
    for f, metric, v, start, end, tag in [
        (ex23, "revenue", 31.2e9, *y23, "Revenue"), (ex24, "revenue", 36.8e9, *y24, "Revenue"),
        (ex24, "net_income", 6.1e9, *y24, "ProfitLoss"),
        (ex24, "total_assets", 70e9, None, y24[1], "Assets"),
    ]:  # fmt: skip
        db.add(_fact(f, metric, v, "EUR", start, end, tag, "ifrs-full"))
    # two companies that went public recently, one a SPAC (as in test_conversation)
    today = date.today()
    for cik, name, ticker, sic, ipo_days in (
        ("0009000001", "Aspen Example Neuro, Inc.", "ASPX", "2834", 20),
        ("0009000002", "Example Acquisition Corp II", "EXAQ", "6770", 40),
    ):
        _company(db, cik, name, ticker, sic)
        db.flush()
        db.add(_filing(cik, 1, "S-1", today - timedelta(days=70)))
        db.add(_filing(cik, 2, "424B4", today - timedelta(days=ipo_days)))
    db.commit()
    marts.build_company_marts(db)
    marts.build_filing_activity(db)
    return db


def _ask(client, auth, case: dict) -> dict:
    routes_chat.chat_limiter.reset()
    routes_chat.chat_day_limiter.reset()
    body = {"message": case["q"]}
    if case.get("as_of"):
        body["as_of"] = case["as_of"]
    r = client.post("/v1/chat", json=body, headers=auth)
    assert r.status_code == 200, (case["id"], r.text)
    return r.json()


def _archive_cites(reply: dict) -> set[int]:
    return {
        c["n"] for c in reply.get("citations") or [] if "sec.gov/Archives" in (c.get("url") or "")
    }


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?!\[)|\n+", text or "") if s.strip()]


def uncited_figures(reply: dict) -> list[str]:
    """Sentences that state a money figure without a citation to a filing."""
    ok = _archive_cites(reply)
    return [s for s in _sentences(reply.get("answer") or "")
            if MONEY.search(s) and not ({int(n) for n in CITE.findall(s)} & ok)]  # fmt: skip


def _cited_sentence_with(reply: dict, needle: str) -> bool:
    ok = _archive_cites(reply)
    return any(needle in s and {int(n) for n in CITE.findall(s)} & ok
               for s in _sentences(reply.get("answer") or ""))  # fmt: skip


def score(case: dict, reply: dict) -> tuple[bool, str]:
    answer = reply.get("answer") or ""
    kind = case["kind"]
    if kind == "figure":
        want = money(case["value"], case["unit"])
        return _cited_sentence_with(reply, want), f"wants {want} in a cited sentence"
    if kind == "ratio":
        want = f"{case['value']:.1f}%"
        return _cited_sentence_with(reply, want), f"wants {want} in a cited sentence"
    if kind == "list":
        blob = answer + json.dumps(reply.get("widgets") or [])
        named = all(n in blob for n in case["names"])
        # the answer itself cites the filings it names (table links alone are not enough)
        linked = bool({int(n) for n in CITE.findall(answer)} & _archive_cites(reply))
        return named and linked, "wants every name and a cited answer"
    if kind == "leadership":
        return bool(answer) and bool(
            {int(n) for n in CITE.findall(answer)} & _archive_cites(reply)
        ), "wants a cited answer"
    if kind in ("no_data", "refusal"):
        return bool(answer) and not MONEY.search(answer), "wants an answer with no figure"
    if kind == "clarify":
        asks = bool(reply.get("suggestions")) or any(
            "company" in n.lower() for n in reply.get("notes") or []
        )
        return not MONEY.search(answer) and asks, "wants no figure and a request to name one"
    if kind == "c06":
        return bool(answer) and bool(_archive_cites(reply)), "C-06: wants a cited answer"
    raise AssertionError(kind)


def test_chat_eval(app, client, auth, eval_db, capsys):
    app.dependency_overrides[get_llm] = lambda: NoModel()
    results = []
    try:
        for case in CASES:
            reply = _ask(client, auth, case)
            passed, why = score(case, reply)
            results.append((case, passed, why, reply, uncited_figures(reply)))
    finally:
        app.dependency_overrides.pop(get_llm, None)

    figure = [r for r in results if r[0]["kind"] in FIGURE_KINDS]
    exact = sum(r[1] for r in figure) / len(figure)
    core = [r for r in results if r[0]["kind"] != "c06"]
    uncited = [(r[0]["id"], s) for r in results for s in r[4]]
    with capsys.disabled():
        print(f"\nC-07: exact figures {sum(r[1] for r in figure)}/{len(figure)} ({exact:.1%}); "
              f"all non-C-06 {sum(r[1] for r in core)}/{len(core)}; "
              f"C-06 {sum(r[1] for r in results if r[0]['kind'] == 'c06')}/6; "
              f"uncited figure sentences {len(uncited)}")  # fmt: skip
        for case, passed, why, reply, _ in results:
            if not passed:
                print(f"  FAIL {case['id']} {case['q']!r}: {why}; got "
                      f"{(reply.get('answer') or '')[:90]!r}")  # fmt: skip

    unexpected = [
        r[0]["id"]
        for r in results
        if not r[1] and r[0]["kind"] != "c06" and r[0]["id"] not in KNOWN_FAILURES
    ]
    fixed = [r[0]["id"] for r in results if r[1] and r[0]["id"] in KNOWN_FAILURES]
    assert not unexpected, f"new failures: {unexpected}"
    assert not fixed, f"now passing, remove from KNOWN_FAILURES: {fixed}"
    assert not [u for u in uncited if u[0] not in KNOWN_FAILURES], f"uncited figures: {uncited}"
    if not any(k in KNOWN_FAILURES for k in (r[0]["id"] for r in figure)):
        assert exact >= 0.95


def test_a_data_answer_with_an_uncited_figure_is_withheld():
    from app.api.routes_chat import _data_reply
    from app.services.conversation import DataAnswer

    text = "Apple Inc. $391.0 billion; Microsoft $245.1 billion."
    bare = _data_reply(DataAnswer(text, "compare"))
    assert "$" not in bare.answer and bare.checks["withheld"].startswith("Apple")
    url = "https://www.sec.gov/Archives/edgar/data/320193/x-index.htm"
    cited = _data_reply(DataAnswer("Apple Inc. $391.0 billion [1].", "compare",
                                   citations=[{"n": 1, "label": "10-K", "url": url}]))  # fmt: skip
    assert cited.answer == "Apple Inc. $391.0 billion [1]." and not cited.checks
