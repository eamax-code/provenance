#!/usr/bin/env python
"""R-2 load smoke: a fixed request rate against a running API, with latency per endpoint.

  python scripts/load_smoke.py --base http://127.0.0.1:8771 --key $KEY --rps 50 --seconds 300

Requests are spread over the endpoints below in turn (facts, screen, search, MCP, the public
overview, the keyed company overview, ownership, stats and coverage), at an open-loop rate:
a slow response never slows the rate.
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
TARGET_P95_MS = {
    "facts": 500,
    "screen": 2000,
    "stats": 100,
    "coverage": 100,
    "search names": 500,
    "search all": 500,
    "executive pay": 500,
    "insider plans": 500,
    "changes": 500,
    "calendar": 500,
    "calendar ciks": 500,
    "corporate tree": 500,
    "comment letters": 500,
    "filing search": 500,
    "insider screen": 500,
}
# the palette's names (ui's check, 2026-11-24) and the read set of 10-K changes
TERMS = (
    "Google",
    "Disney",
    "Coca-Cola",
    "Meta",
    "Lucid",
    "Honeywell",
    "Ford",
    "Target",
    "apple",
    "Pepsi",
)
READ = ("320193", "789019", "19617", "1067983", "1326801", "12927")


# Q-01: 15 query shapes (words, phrases, a quoted word, or-groups, exclusions, filters), each in
# both sorts: 30 shapes
FILING_QUERIES = (
    "tariffs", "%22going%20concern%22", "%22material%20weakness%22",
    "%22supply%20chain%22%20disruption", "%22artificial%20intelligence%22%20-crypto",
    "layoffs%20or%20restructuring", "%22reverse%20stock%20split%22", "revenue",
    "%22interest%20rate%22%20-inflation", "cybersecurity&section=annual_report",
    "%22going%20concern%22&form=S-1,F-1", "tariffs&filed_from=2026-01-01&filed_to=2026-06-30",
    "%22will%20be%20available%22", "guidance%20or%20outlook&section=earnings_release",
    "%22risk%20factors%22&cik=320193",
)  # fmt: skip
# Q-03: the default screen and filtered shapes (dates fixed, so every run reads the same data)
INSIDER_SCREENS = (
    "since=2026-10-25&until=2026-11-24",
    "type=buy&since=2026-08-26&until=2026-11-24&min_value=1000000&sort=value",
    "type=sell&since=2026-10-25&until=2026-11-24&title=chief%20executive,chief%20financial,ceo,cfo",
    "type=buy&cluster=true&since=2026-08-26&until=2026-11-24",
    "type=sell&since=2025-11-23&until=2026-11-24&plan_10b5_1=false&min_value=5000000&sort=value",
    "role=director&since=2026-10-25&until=2026-11-24&sort=filed",
    "cik=320193&since=2025-11-23&until=2026-11-24",
)  # fmt: skip
SHOWCASE_PAGES = ("overview", "statements/income", "timeline", "insiders", "holders", "ownership")


def demo_request_for(i: int, ciks: tuple[str, ...]) -> tuple[str, str, str, dict | None]:
    """The keyless burst: every showcase page for every showcase company, in turn."""
    page = SHOWCASE_PAGES[i % len(SHOWCASE_PAGES)]
    cik = ciks[(i // len(SHOWCASE_PAGES)) % len(ciks)]
    return f"demo {page.split('/')[0]}", "GET", f"/v1/companies/{cik}/{page}", None


def requests_for(
    i: int, only: list[str] | None = None, watchlist: str | None = None
) -> tuple[str, str, str, dict | None]:
    """(name, method, path, json body) for the i-th request, over `only` endpoints if given."""
    cik = CIKS[i % len(CIKS)]
    plan = [
        ("facts", "GET", f"/v1/companies/{cik}/facts?metric=revenue&period=annual&limit=20", None),
        ("screen", "GET", "/v1/facts/screen?metric=revenue&year=2025&limit=50", None),
        ("search", "GET", "/v1/companies/search?q=apple&limit=10", None),
        ("mcp", "POST", "/mcp", {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                 "params": {"name": "get_figures",
                                            "arguments": {"cik": cik, "metric": "net_income"}}}),
        ("overview", "GET", f"/v1/public/companies/{cik}/overview", None),
        ("company", "GET", f"/v1/companies/{cik}", None),
        ("ownership", "GET", f"/v1/companies/{cik}/ownership", None),
        ("stats", "GET", "/v1/stats", None),
        ("coverage", "GET", "/v1/public/coverage", None),
        ("timeline", "GET", f"/v1/companies/{cik}/timeline?limit=50", None),
        ("statements", "GET", f"/v1/companies/{cik}/statements/income?period=annual", None),
        ("keyed overview", "GET", f"/v1/companies/{cik}/overview", None),
        ("search names", "GET", f"/v1/companies/search?q={TERMS[i % len(TERMS)]}&limit=8", None),
        ("search all", "GET", f"/v1/search?q={TERMS[i % len(TERMS)]}", None),
        ("executive pay", "GET", f"/v1/companies/{cik}/executive-pay", None),
        ("insider plans", "GET", f"/v1/companies/{cik}/insider-plans", None),
        ("changes", "GET", f"/v1/companies/{READ[i % len(READ)]}/changes", None),
        ("calendar", "GET", f"/v1/companies/{cik}/calendar", None),
        ("calendar ciks", "GET", "/v1/calendar?ciks=320193,789019,19617,1067983,1326801", None),
        ("corporate tree", "GET", f"/v1/companies/{cik}/corporate-tree", None),
        ("comment letters", "GET", f"/v1/companies/{cik}/comment-letters", None),
        ("insider screen", "GET", f"/v1/insider-transactions?{INSIDER_SCREENS[i % 7]}", None),
        ("filing search", "GET", f"/v1/search/filings?q={FILING_QUERIES[i % 15]}"
                                 f"&sort={('date', 'relevance')[i // 15 % 2]}", None),
    ]  # fmt: skip
    if watchlist:
        plan.append(("watchlist rows", "GET", f"/v1/watchlists/{watchlist}/rows", None))
    if only:
        plan = [p for p in plan if p[0] in only]
    return plan[i % len(plan)]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8771")
    ap.add_argument("--key", default="", help="An API key (not the demo key: it is capped)")
    ap.add_argument("--rps", type=float, default=50)
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--endpoints", default="", help="comma-separated names (default: all)")
    ap.add_argument("--watchlist", default=None, help="a watchlist id of --key, for its /rows")
    ap.add_argument(
        "--demo",
        default="",
        help="keyless burst: comma-separated showcase CIKs, "
        "read with the demo key (repeat views are served from the server's cache)",
    )
    args = ap.parse_args()
    demo_ciks = tuple(c for c in args.demo.split(",") if c)
    only = [e for e in args.endpoints.split(",") if e] or None
    results: dict[str, list[float]] = {}
    errors: dict[str, dict[str, int]] = {}
    lock = threading.Lock()
    client = httpx.Client(base_url=args.base, timeout=30,
                          headers={"X-API-Key": "demo" if demo_ciks else args.key},
                          limits=httpx.Limits(max_connections=args.workers))  # fmt: skip

    def one(i: int) -> None:
        name, method, path, body = (
            demo_request_for(i, demo_ciks) if demo_ciks else requests_for(i, only, args.watchlist)
        )
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
