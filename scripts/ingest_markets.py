#!/usr/bin/env python
"""Ingest international listing sources (Canada / Europe / UK).

  python scripts/ingest_markets.py --source esma_firds [--days-back 3]
  python scripts/ingest_markets.py --source fca_firds
  python scripts/ingest_markets.py --source gleif [--limit 50]      # issuer enrichment
  python scripts/ingest_markets.py --source tsx | cse   # only when enabled (see below)
  python scripts/ingest_markets.py --all                 # every enabled source, in order
  python scripts/ingest_markets.py --loop                # daily at MARKETS_DAILY_HOUR_UTC, forever

Sources run only when listed in MARKETS_SOURCES_ENABLED. Exchange feeds (tsx, cse) carry
non-commercial terms; enabling them states that you hold the required permission.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from _bootstrap import bootstrap

from app.jobs import markets as markets_job
from app.services.markets import canada, firds, gleif
from app.services.markets.http import MarketHttp

ORDER = ("esma_firds", "fca_firds", "tsx", "cse", "gleif")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", choices=ORDER)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--loop", action="store_true", help="Run --all once per day, forever")
    parser.add_argument("--days-back", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="GLEIF lookups this run")
    parser.add_argument("--full", action="store_true", help="FIRDS: also process FULINS files")
    args = parser.parse_args()
    if not args.source and not args.all and not args.loop:
        parser.error("choose --source, --all or --loop")
    settings, Session = bootstrap()
    if args.loop:
        while True:
            db = Session()
            try:
                out = markets_job.maybe_run(db, settings)
                if out is not None:
                    print(json.dumps(out, default=str))
            finally:
                db.close()
            time.sleep(min(3600, markets_job.seconds_until_next_run(settings)))
    if args.all:
        db = Session()
        try:
            print(json.dumps(markets_job.run_all(db, settings), default=str))
            return 0
        finally:
            db.close()
    enabled = {s.strip() for s in settings.markets_sources_enabled.split(",") if s.strip()}
    sources = [s for s in ORDER if s in enabled] if args.all else [args.source]
    db = Session()
    http = MarketHttp(settings)
    exit_code = 0
    try:
        for source in sources:
            if source not in enabled:
                print(f"{source}: not enabled (MARKETS_SOURCES_ENABLED); skipping", file=sys.stderr)
                exit_code = 2
                continue
            if source in ("esma_firds", "fca_firds"):
                types = ("DLTINS", "FULINS") if args.full else ("DLTINS",)
                out = firds.ingest_firds(
                    db, settings, http, source, days_back=args.days_back, file_types=types
                )
            elif source == "gleif":
                out = gleif.enrich_issuers(db, settings, http, limit=args.limit)
            else:
                out = canada.ingest_source(db, settings, http, source)
            print(json.dumps({"source": source, **out}, default=str))
        return exit_code
    finally:
        http.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
