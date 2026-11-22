#!/usr/bin/env python
"""R-2 load smoke: a fixed request rate against a running API, with latency per endpoint.

  python scripts/load_smoke.py --base http://127.0.0.1:8771 --key $KEY --rps 50 --seconds 300

Requests are spread over the endpoints below in turn (facts, screen, search, MCP, the public
overview, stats and coverage), at an open-loop rate: a slow response never slows the rate.
Prints p50/p95/p99, errors and the targets (p95: facts < 500 ms, screen < 2 s, stats and
coverage < 100 ms) as JSON.
"""

from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

CIKS = ("320193", "789019", "19617", "1326160", "726728", "1067983")
TARGET_P95_MS = {"facts": 500, "screen": 2000, "stats": 100, "coverage": 100}


def requests_for(i: int) -> tuple[str, str, str, dict | None]:
    """(name, method, path, json body) for the i-th request."""
    cik = CIKS[i % len(CIKS)]
    plan = [
        ("facts", "GET", f"/v1/companies/{cik}/facts?metric=revenue&period=annual&limit=20", None),
        ("screen", "GET", "/v1/facts/screen?metric=revenue&year=2025&limit=50", None),
        ("search", "GET", "/v1/companies/search?q=apple&limit=10", None),
        ("mcp", "POST", "/mcp", {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                 "params": {"name": "get_figures",
                                            "arguments": {"cik": cik, "metric": "net_income"}}}),
        ("overview", "GET", f"/v1/public/companies/{cik}/overview", None),
        ("stats", "GET", "/v1/stats", None),
        ("coverage", "GET", "/v1/public/coverage", None),
    ]  # fmt: skip
    return plan[i % len(plan)]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8771")
    ap.add_argument("--key", required=True, help="An API key (not the demo key: it is capped)")
    ap.add_argument("--rps", type=float, default=50)
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--workers", type=int, default=64)
    args = ap.parse_args()
    results: dict[str, list[float]] = {}
    errors: dict[str, dict[str, int]] = {}
    lock = threading.Lock()
    client = httpx.Client(base_url=args.base, timeout=30,
                          headers={"X-API-Key": args.key},
                          limits=httpx.Limits(max_connections=args.workers))  # fmt: skip

    def one(i: int) -> None:
        name, method, path, body = requests_for(i)
        start = time.perf_counter()
        try:
            r = client.request(method, path, json=body)
            status = str(r.status_code)
        except httpx.HTTPError as exc:
            status = type(exc).__name__
        ms = (time.perf_counter() - start) * 1000
        with lock:
            results.setdefault(name, []).append(ms)
            if not status.startswith("2"):
                errors.setdefault(name, {})[status] = errors.setdefault(name, {}).get(status, 0) + 1

    total = int(args.rps * args.seconds)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i in range(total):
            due = t0 + i / args.rps
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            pool.submit(one, i)
    elapsed = time.perf_counter() - t0
    out = {"requests": total, "seconds": round(elapsed, 1),
           "achieved_rps": round(total / elapsed, 1), "endpoints": {}}  # fmt: skip
    for name, ms in sorted(results.items()):
        p95 = pct(ms, 0.95)
        target = TARGET_P95_MS.get(name)
        out["endpoints"][name] = {
            "n": len(ms), "p50": pct(ms, 0.5), "p95": p95, "p99": pct(ms, 0.99),
            "mean": round(statistics.fmean(ms), 1), "errors": errors.get(name, {}),
            "target_p95": target, "pass": None if target is None else bool(p95 and p95 < target),
        }  # fmt: skip
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
