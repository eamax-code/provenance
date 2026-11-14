"""What a backtest would have known: a screen run "as of" a past date against the same screen
with today's data. Needs the Python client (clients/python) and your own key.

    PROVENANCE_API_KEY=prv_... PROVENANCE_BASE_URL=https://... python examples/point_in_time.py \
        --metric revenue --year 2023 --as-of 2024-03-31

Every company in today's ranking whose figure was filed after the as-of date is look-ahead: a
backtest that used it would have traded on information nobody had yet. Restated values show the
same problem one figure at a time.
"""

from __future__ import annotations

import argparse

from provenance_client import Client


def compare(client: Client, metric: str, year: int, as_of: str, top: int) -> dict:
    then = {r["cik"]: r for r in client.screen(metric, year, as_of=as_of)}
    now = {r["cik"]: r for r in client.screen(metric, year)}
    unknown = [r for cik, r in now.items() if cik not in then]
    restated = [
        (then[cik], r) for cik, r in now.items() if cik in then and then[cik]["value"] != r["value"]
    ]
    ranked_now = sorted(now.values(), key=lambda r: r["value"] or 0, reverse=True)[:top]
    return {"then": then, "now": now, "unknown": unknown, "restated": restated, "top": ranked_now}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--metric", default="revenue")
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--as-of", default="2024-03-31")
    ap.add_argument("--top", type=int, default=100, help="size of the 'top N' portfolio")
    args = ap.parse_args()
    with Client() as client:
        r = compare(client, args.metric, args.year, args.as_of, args.top)
    print(
        f"{args.metric}, calendar {args.year}: {len(r['now']):,} companies today, "
        f"{len(r['then']):,} known on {args.as_of}."
    )
    print(f"Look-ahead: {len(r['unknown']):,} companies' figures were filed after {args.as_of}.")
    late_in_top = [x for x in r["top"] if x["cik"] not in r["then"]]
    print(
        f"Of today's top {args.top}, {len(late_in_top)} could not have been picked on {args.as_of}."
    )
    print(f"Restated since then: {len(r['restated']):,} companies.")
    for before, after in r["restated"][:5]:
        name = after.get("ticker") or after.get("legal_name") or after["cik"]
        print(
            f"  {name}: {before['value']:,} (filed {before['filed_date']}) -> "
            f"{after['value']:,} (filed {after['filed_date']}, {after['source_url']})"
        )


if __name__ == "__main__":
    main()
