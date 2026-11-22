"""C-01: the versioned chat reply (docs/chat-reply-schema.md): blocks, figure chips, how."""

from __future__ import annotations

from app.api import routes_chat
from app.api.routes_chat import get_llm
from tests.integration.test_chat_eval import NoModel


def _ask(app, client, auth, message, **extra):
    routes_chat.chat_limiter.reset()
    routes_chat.chat_day_limiter.reset()
    app.dependency_overrides[get_llm] = lambda: NoModel()
    try:
        r = client.post("/v1/chat", json={"message": message, **extra}, headers=auth)
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_figure_answer_carries_a_chip_with_its_provenance_card(app, client, auth, items_aapl):
    body = _ask(app, client, auth, "Apple revenue 2024")
    assert body["schema_version"] == "2"
    assert body["answer"] and body["citations"]  # version-1 fields unchanged
    text, chips = body["blocks"][0], [b for b in body["blocks"] if b["type"] == "figure"]
    assert text["type"] == "text" and text["text"] == body["answer"] and text["citations"]
    chip = next(c for c in chips if c["period_end"] == "2024-09-28")
    assert chip["metric"] == "revenue" and chip["display"] == "$391.0 billion"
    for field in ("source_url", "source_tag", "mapping_version", "accession_number",
                  "quality_status", "form_type", "filed_date"):  # fmt: skip
        assert chip[field], field
    cites = {c["n"]: c["url"] for c in body["citations"]}
    assert cites[chip["citation"]] == chip["source_url"]
    assert body["how"] == [{"endpoint": "/v1/companies/320193/facts",
                            "parameters": {"metric": "revenue", "period": "annual"},
                            "as_of": None}]  # fmt: skip


def test_margin_chips_show_both_inputs_and_how_names_the_ratio(app, client, auth, items_aapl):
    body = _ask(app, client, auth, "What is Apple's operating margin?", as_of="2024-12-31")
    metrics = {b["metric"] for b in body["blocks"] if b["type"] == "figure"}
    assert metrics == {"operating_income", "revenue"}
    assert body["how"][0]["parameters"]["metric"] == "operating_margin"
    assert body["how"][0]["as_of"] == "2024-12-31"


def test_every_reply_has_blocks_even_without_figures(app, client, auth, items_aapl):
    body = _ask(app, client, auth, "Should I buy Apple stock?")
    assert body["schema_version"] == "2" and [b["type"] for b in body["blocks"]] == ["text"]
    assert body["how"] == []
