"""Saved conversations: kept per API key, private to it, never for the demo key."""

from __future__ import annotations

from app.services.llm import LLMReply


class FakeLLM:
    def chat(self, messages, **kw):
        return LLMReply(
            text="Revenue was $391.0 billion [2].", model="fake:1b", duration_ms=1, output_tokens=5
        )


def _ask(client, headers, message, **extra):
    r = client.post("/v1/chat", json={"message": message, **extra}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_conversation_is_saved_and_continued(app, client, auth, items_aapl):
    app.state.llm_factory = FakeLLM
    first = _ask(client, auth, "How is Apple's revenue growing?")
    sid = first["session_id"]
    assert sid
    second = _ask(client, auth, "And net income?", session_id=sid, cik="320193")
    assert second["session_id"] == sid
    listed = client.get("/v1/chat/sessions", headers=auth).json()["data"]
    assert [s["id"] for s in listed] == [sid]
    assert listed[0]["title"] == "How is Apple's revenue growing?"
    assert listed[0]["company_cik"] == "0000320193"
    full = client.get(f"/v1/chat/sessions/{sid}", headers=auth).json()
    assert [m["role"] for m in full["messages"]] == ["user", "assistant"] * 2
    assert full["messages"][1]["reply"]["brief"]["metrics"]
    assert "session_id" not in full["messages"][1]["reply"]


def test_sessions_are_private_to_their_key(app, client, auth, db, settings, items_aapl):
    from app.services.api_keys import create_key_record

    app.state.llm_factory = FakeLLM
    sid = _ask(client, auth, "Apple revenue")["session_id"]
    _, other = create_key_record(db, settings, "other@example.com", "free", "t", actor="test")
    db.commit()
    other_auth = {"X-API-Key": other}
    assert client.get(f"/v1/chat/sessions/{sid}", headers=other_auth).status_code == 404
    r = client.post("/v1/chat", json={"message": "Apple", "session_id": sid}, headers=other_auth)
    assert r.status_code == 404
    assert client.get("/v1/chat/sessions", headers=other_auth).json()["data"] == []


def test_demo_key_saves_nothing(app, client, settings, items_aapl):
    settings.public_showcase_ciks = "320193"
    app.state.llm_factory = FakeLLM
    demo = {"X-API-Key": "demo"}
    assert _ask(client, demo, "Apple revenue")["session_id"] is None
    r = client.post(
        "/v1/chat",
        json={"message": "Apple", "session_id": "00000000-0000-0000-0000-000000000001"},
        headers=demo,
    )
    assert r.status_code == 403
    assert client.get("/v1/chat/sessions", headers=demo).status_code == 401


def test_delete_session(app, client, auth, items_aapl):
    app.state.llm_factory = FakeLLM
    sid = _ask(client, auth, "Apple revenue")["session_id"]
    assert client.delete(f"/v1/chat/sessions/{sid}", headers=auth).status_code == 204
    assert client.get(f"/v1/chat/sessions/{sid}", headers=auth).status_code == 404
