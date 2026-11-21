#!/usr/bin/env python
"""Production smoke test (launch plan I-09): run every promise end to end against a server.

  PRV_KEY=<builder key> python scripts/smoke_prod.py --base https://api.example --receiver 8099

Checks readiness, the demo key's limits, a keyed figure with as_of, the plans, MCP tools/list and
one call, the live event stream, a type watch, and a signed webhook delivered to a receiver this
script runs on --receiver (the server must be allowed to reach it; for a local rehearsal set
WEBHOOK_ALLOW_PRIVATE_DESTINATIONS=true on the server, never in production). Prints one line per
check and a summary; --report appends it to docs/pilot-report.md.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.security import verify_webhook_signature  # noqa: E402

RESULTS: list[dict] = []


def check(name: str):
    def wrap(fn):
        def run(*a, **k):
            t = time.perf_counter()
            try:
                detail = fn(*a, **k) or ""
                ok = True
            except Exception as exc:  # noqa: BLE001 - each check reports its own failure
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            ms = round((time.perf_counter() - t) * 1000)
            RESULTS.append({"check": name, "ok": ok, "ms": ms, "detail": str(detail)[:200]})
            print(f"{'PASS' if ok else 'FAIL'}  {name:<34} {ms:>6} ms  {detail}", flush=True)

        return run

    return wrap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--receiver", type=int, default=0, help="port for the webhook receiver")
    ap.add_argument(
        "--receiver-host",
        default="127.0.0.1",
        help="how the server reaches this machine (host.docker.internal from Docker)",
    )
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("PRV_KEY", "")
    h = {"X-API-Key": key}
    c = httpx.Client(base_url=args.base, timeout=30)

    @check("readyz")
    def readyz():
        r = c.get("/readyz")
        body = r.json()
        assert r.status_code == 200, body
        return body.get("status")

    @check("demo key: data and limits")
    def demo():
        r = c.get("/v1/companies/320193/facts?metric=revenue", headers={"X-API-Key": "demo"})
        assert r.status_code == 200, r.text[:200]
        return f"limit {r.headers.get('X-RateLimit-Limit')}/min, rows {len(r.json()['data'])}"

    @check("keyed facts with as_of")
    def facts():
        r = c.get("/v1/companies/320193/facts?metric=revenue&as_of=2024-01-15", headers=h)
        assert r.status_code == 200 and r.json()["as_of"] == "2024-01-15", r.text[:200]
        top = r.json()["data"][0]
        assert top["filed_date"] <= "2024-01-15"
        return f"{top['period_label']} {top['value']} filed {top['filed_date']}"

    @check("plans")
    def plans():
        names = [p["name"] for p in c.get("/v1/public/plans").json()["data"]]
        assert names == ["free", "analyst", "builder", "team", "enterprise"], names
        return ", ".join(names)

    @check("MCP tools/list and a call")
    def mcp():
        mh = {**h, "Accept": "application/json, text/event-stream"}
        lst = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = [t["name"] for t in lst.json()["result"]["tools"]]
        call = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": tools[0], "arguments": {"query": "apple"}}})  # fmt: skip
        assert call.status_code == 200 and "result" in call.json(), call.text[:200]
        return f"{len(tools)} tools"

    @check("event stream (SSE)")
    def sse():
        got = []
        with c.stream("GET", "/v1/events/stream", headers=h, timeout=20) as r:
            assert r.status_code == 200, r.status_code
            start = time.time()
            for line in r.iter_lines():
                if line:
                    got.append(line)
                if time.time() - start > 8 or len(got) >= 2:
                    break
        return f"{len(got)} lines, first {got[0][:40] if got else 'none'}"

    @check("type watch (Builder)")
    def type_watch():
        r = c.post("/v1/type-watches", headers=h, json={"event_types": ["sec.restatement"],
                   "destination": "https://hooks.example.com/smoke"})  # fmt: skip
        assert r.status_code == 201, r.text[:200]
        c.delete(f"/v1/type-watches/{r.json()['id']}", headers=h)
        return r.json()["delivery_mode"]

    @check("signed webhook to a receiver")
    def webhook():
        if not args.receiver:
            return "skipped (no --receiver)"
        received: list[tuple[dict, bytes]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                received.append((dict(self.headers), body))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("0.0.0.0", args.receiver), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            dest = f"http://{args.receiver_host}:{args.receiver}/hook"
            w = c.post("/v1/watches", headers=h, json={"cik": "320193",
                       "destination_type": "webhook", "destination": dest})  # fmt: skip
            assert w.status_code == 201, w.text[:200]
            wid, secret = w.json()["id"], w.json()["webhook_secret"]
            t = c.post(f"/v1/watches/{wid}/test", headers=h)
            c.delete(f"/v1/watches/{wid}", headers=h)
            assert t.status_code == 200 and t.json()["delivered"], t.text[:200]
            hdrs, body = received[0]
            ok = verify_webhook_signature(secret, hdrs["X-Signature-Timestamp"],
                                          hdrs["X-Signature"], body)  # fmt: skip
            assert ok, "signature did not verify"
            return f"delivered and verified ({hdrs['X-Event-Type']})"
        finally:
            srv.shutdown()

    for fn in (readyz, demo, facts, plans, mcp, sse, type_watch, webhook):
        fn()
    passed = sum(r["ok"] for r in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed against {args.base}")
    if args.report:
        lines = [f"\n## Production smoke, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC\n",
                 f"Against `{args.base}` (production settings), `scripts/smoke_prod.py`.\n",
                 "| Check | Result | Time | Detail |", "| --- | --- | --- | --- |"]  # fmt: skip
        lines += [f"| {r['check']} | {'pass' if r['ok'] else 'FAIL'} | {r['ms']} ms | "
                  f"{r['detail'].replace('|', '/')} |" for r in RESULTS]  # fmt: skip
        with open(ROOT / "docs" / "pilot-report.md", "a") as f:
            f.write("\n".join(lines) + f"\n\n{passed} of {len(RESULTS)} checks passed.\n")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
