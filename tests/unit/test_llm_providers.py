"""The model can run locally (Ollama) or behind an OpenAI-compatible API (GH #13)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.llm import LLMUnavailable, LocalLLM


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compatible_provider(settings, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        choice = {"message": {"content": "Revenue rose [1]."}}
        body = {"model": "m-1", "usage": {"completion_tokens": 7}, "choices": [choice]}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example/v1/")
    monkeypatch.setattr(settings, "llm_model", "m-1")
    reply = LocalLLM(settings, http=_client(handler)).chat(
        [{"role": "user", "content": "hi"}], schema={"type": "object"}, max_tokens=50
    )
    assert reply.text == "Revenue rose [1]." and reply.output_tokens == 7 and reply.model == "m-1"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["max_tokens"] == 50 and seen["body"]["model"] == "m-1"
    assert seen["body"]["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_openai_errors_become_unavailable(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    llm = LocalLLM(settings, http=_client(lambda r: httpx.Response(429, json={})))
    with pytest.raises(LLMUnavailable, match="429"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_ollama_stays_the_default(settings, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"model": "q", "message": {"content": "ok"}})

    monkeypatch.setattr(settings, "llm_enabled", True)
    assert settings.llm_provider == "ollama"
    assert (
        LocalLLM(settings, http=_client(handler)).chat([{"role": "user", "content": "x"}]).text
        == "ok"
    )
    assert seen["url"].endswith("/api/chat")


def test_readiness_flags_a_missing_model_key_and_console_email(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert "LLM_PROVIDER=openai needs LLM_API_KEY" in settings.validate_for_runtime()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "email_provider", "console")
    assert any("EMAIL_PROVIDER=console" in p for p in settings.validate_for_runtime())
