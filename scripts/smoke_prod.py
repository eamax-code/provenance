#!/usr/bin/env python
"""Production smoke test (launch plan I-09): run every promise end to end against a server.

  PRV_KEY=<builder key> python scripts/smoke_prod.py --base https://api.example --receiver 8099

Checks readiness, the demo key's limits, a keyed figure with as_of, the plans, MCP tools/list and
one call, the live event stream, a type watch, a signed webhook delivered to a receiver this
script runs on --receiver (the server must be allowed to reach it; for a local rehearsal set
WEBHOOK_ALLOW_PRIVATE_DESTINATIONS=true on the server, never in production), and the Explorer
endpoints (statements, timeline, keyed overview, watchlists, their MCP tools, the cached keyless
showcase). Prints one line per check and a summary; --report appends it to docs/pilot-report.md.
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
from app.services.sec_client import ARCHIVES_BASE  # noqa: E402

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

    archives = ARCHIVES_BASE

    @check("statements (X-02)")
    def statements():
        r = c.get("/v1/companies/320193/statements/income?periods=14", headers=h)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        cells = [x for row in body["rows"] if not row["derived"] for x in row["cells"] if x]
        assert cells and all(x["source_url"].startswith(archives) for x in cells)
        brk = next((row["split_break"] for row in body["rows"] if row.get("split_break")), None)
        where = brk and brk["between"]
        return f"{len(body['columns'])} columns, {len(body['rows'])} rows, split_break {where}"

    @check("timeline (X-05) and its cursor")
    def timeline():
        r = c.get("/v1/companies/320193/timeline?limit=10", headers=h)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        nxt = c.get(f"/v1/companies/320193/timeline?limit=10&cursor={body['meta']['next_cursor']}",
                    headers=h).json()  # fmt: skip
        ids = {i["id"] for i in body["data"]}
        assert nxt["data"] and not ids & {i["id"] for i in nxt["data"]}, "pages overlap"
        newest = body["data"][0]["title"][:40]
        return f"{len(body['data'])}+{len(nxt['data'])} items, newest {newest}"

    @check("keyed overview (X-01a)")
    def keyed_overview():
        r = c.get("/v1/companies/320193/overview", headers=h)
        assert r.status_code == 200, r.text[:200]
        assert "no-store" in r.headers.get("Cache-Control", ""), r.headers.get("Cache-Control")
        return f"{len(r.content) // 1024} KB, keys {len(r.json())}"

    @check("watchlist create, rows, delete (X-07)")
    def watchlist():
        body = {"name": "smoke", "ciks": ["320193", "789019"], "columns": ["revenue", "last_event"]}
        r = c.post("/v1/watchlists", headers=h, json=body)
        assert r.status_code == 201, r.text[:200]
        wid = r.json()["id"]
        try:
            rows = c.get(f"/v1/watchlists/{wid}/rows", headers=h)
            assert rows.status_code == 200, rows.text[:200]
            rev = rows.json()["data"][0]["cells"]["revenue"]
            assert rev["source_url"].startswith(archives), rev
        finally:
            gone = c.delete(f"/v1/watchlists/{wid}", headers=h)
        assert gone.status_code == 204, gone.status_code
        return f"{len(rows.json()['data'])} rows, deleted"

    @check("MCP company_statements and company_timeline")
    def mcp_new():
        import json as _json

        mh = {**h, "Accept": "application/json, text/event-stream"}
        out = []
        for i, (name, args_) in enumerate((
            ("company_statements", {"cik": "320193", "statement": "income", "periods": 5}),
            ("company_timeline", {"cik": "320193", "limit": 5}),
        )):  # fmt: skip
            call = {"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                    "params": {"name": name, "arguments": args_}}  # fmt: skip
            r = c.post("/mcp", headers=mh, json=call)
            res = r.json()["result"]
            assert res["isError"] is False, res
            out.append(f"{name} {len(_json.loads(res['content'][0]['text']))} keys")
        return ", ".join(out)

    @check("keyless showcase (cached)")
    def showcase():
        demo_h = {"X-API-Key": "demo"}
        first = c.get("/v1/companies/320193/timeline", headers=demo_h)
        again = c.get("/v1/companies/320193/timeline", headers=demo_h)
        assert first.status_code == again.status_code == 200, first.text[:200]
        assert again.headers.get("X-Cache") == "hit", again.headers.get("X-Cache")
        return f"first {first.headers.get('X-Cache')}, then hit"

    for fn in (readyz, demo, facts, plans, mcp, sse, type_watch, webhook, statements, timeline,
               keyed_overview, watchlist, mcp_new, showcase):  # fmt: skip
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
