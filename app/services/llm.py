"""Local language model client (Ollama HTTP API). Nothing leaves the machine it runs on.

Default model: Qwen3 4B Instruct 2507 (Apache-2.0, non-thinking), small enough for a laptop
or a modest CPU/GPU host.
The model only phrases answers from context we assemble; it is never a source of facts.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Drop reasoning traces that thinking models emit even when asked not to."""
    text = _THINK.sub("", text)
    if "</think>" in text:  # opening tag already stripped by the server
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


class LLMUnavailable(Exception):
    """The local model server is disabled, unreachable or returned an error."""


@dataclass
class LLMReply:
    text: str
    model: str
    duration_ms: int
    output_tokens: int | None


class LocalLLM:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=3.0)
        )

    def chat(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> LLMReply:
        if not self.settings.llm_enabled:
            raise LLMUnavailable("The local language model is disabled on this deployment.")
        body: dict = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            "think": False,  # answers, not reasoning traces; much faster on small models
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens or self.settings.llm_max_answer_tokens,
            },
        }
        if schema is not None:
            body["format"] = schema
        started = time.monotonic()
        try:
            r = self.http.post(self.settings.llm_base_url.rstrip("/") + "/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise LLMUnavailable("The local language model could not be reached.") from exc
        if r.status_code != 200:
            raise LLMUnavailable(f"The local language model returned HTTP {r.status_code}.")
        data = r.json()
        return LLMReply(
            text=strip_reasoning((data.get("message") or {}).get("content", "")),
            model=data.get("model", self.settings.llm_model),
            duration_ms=int((time.monotonic() - started) * 1000),
            output_tokens=data.get("eval_count"),
        )
