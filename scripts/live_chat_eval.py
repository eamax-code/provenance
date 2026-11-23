#!/usr/bin/env python
"""Live chat eval (C-07, not CI): 20 questions against a real database, no model.

  python scripts/live_chat_eval.py                          # the database in DATABASE_URL
  python scripts/live_chat_eval.py --database-url URL       # e.g. a scratch restore
  python scripts/live_chat_eval.py --json out.json          # also write the answers

Expected values in tests/fixtures/chat_eval/live.json are checked against the filings. Runs the
app in-process with on-demand SEC fetching off; no API key is created. Prints one line per case
and a summary: exact figures, cited answers, uncited figure sentences.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = ROOT / "tests" / "fixtures" / "chat_eval" / "live.json"
MONEY = re.compile(r"(?:\$|\b[A-Z]{3} )-?[\d,]+(?:\.\d+)? (?:trillion|billion|million)\b")
CITE = re.compile(r"\[(\d+)\]")


class NoModel:
    def chat(self, messages, **kw):
        from app.services.llm import LLMUnavailable

        raise LLMUnavailable("No model in the live eval: the deployed default.")


def _archive(reply: dict) -> set[int]:
    return {
        c["n"] for c in reply.get("citations") or [] if "sec.gov/Archives" in (c.get("url") or "")
    }


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?!\[)|\n+", text or "") if s.strip()]


def uncited(reply: dict) -> list[str]:
    ok = _archive(reply)
    return [s for s in _sentences(reply.get("answer") or "")
            if MONEY.search(s) and not ({int(n) for n in CITE.findall(s)} & ok)]  # fmt: skip


def score(case: dict, reply: dict) -> bool:
    from app.services.intel import money

    answer, ok = reply.get("answer") or "", _archive(reply)
    cited = [s for s in _sentences(answer) if {int(n) for n in CITE.findall(s)} & ok]
    kind = case["kind"]
    if kind == "figure":
        return any(money(case["value"], case["unit"]) in s for s in cited)
    if kind == "cited_percentages":
        return sum(len(re.findall(r"\d+\.\d%", s)) for s in cited) >= case["count"]
    if kind == "cited":
        return bool(cited)
    if kind == "refusal":
        return bool(answer) and not MONEY.search(answer)
    if kind == "company":  # which company the question was resolved to (no figure checked)
        return (reply.get("company") or {}).get("cik") == case["company_cik"]
    raise ValueError(kind)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--json", default=None, help="write each case's answer here")
    args = ap.parse_args()
    from fastapi.testclient import TestClient

    from app.api import routes_chat
    from app.api.dependencies import require_reader
    from app.core.config import get_settings
    from app.main import create_app

    overrides = {"on_demand_ingestion_enabled": False}
    if args.database_url:
        overrides["database_url"] = args.database_url
    settings = get_settings().model_copy(update=overrides)
    app = create_app(settings)
    app.state.llm_factory = lambda: NoModel()
    app.dependency_overrides[require_reader] = lambda: SimpleNamespace(
        id=None, plan="enterprise", owner_email=None
    )
    cases = json.loads(CASES.read_text())["cases"]
    out, figures, passed, bad = [], 0, 0, []
    with TestClient(app) as client:
        for case in cases:
            routes_chat.chat_limiter.reset()
            routes_chat.chat_day_limiter.reset()
            body = {"message": case["q"], **({"as_of": case["as_of"]} if case.get("as_of") else {}),
                    **({"cik": case["cik"]} if case.get("cik") else {})}  # an Ask link's cik
            r = client.post("/v1/chat", json=body)
            reply = r.json() if r.status_code == 200 else {"answer": None, "error": r.text[:200]}
            ok = r.status_code == 200 and score(case, reply)
            figures += case["kind"] == "figure"
            passed += ok
            bad += [(case["id"], s) for s in uncited(reply)]
            print(f"{'PASS' if ok else 'FAIL'} {case['id']} {case['q']!r}"
                  f"{' as_of ' + case['as_of'] if case.get('as_of') else ''}: "
                  f"{(reply.get('answer') or reply.get('error') or '')[:150]!r}")  # fmt: skip
            out.append({**case, "passed": ok, "answer": reply.get("answer"),
                        "citations": reply.get("citations")})  # fmt: skip
    exact = sum(1 for o in out if o["kind"] == "figure" and o["passed"])
    print(json.dumps({"cases": len(cases), "passed": passed, "exact_figures": f"{exact}/{figures}",
                      "uncited_figure_sentences": len(bad)}))  # fmt: skip
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1, default=str))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
