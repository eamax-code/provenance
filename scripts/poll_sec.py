#!/usr/bin/env python
"""Poll the SEC for watched companies and deliver pending notifications.

Usage: python scripts/poll_sec.py --once          # one pass (cron-friendly)
       python scripts/poll_sec.py                 # loop every INGESTION_POLL_INTERVAL_SECONDS
       python scripts/poll_sec.py --once --all    # refresh every ingested company, not just watched
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap

from app.jobs.poll_sec import run_forever, run_once


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--all", action="store_true", help="Poll all ingested companies")
    args = parser.parse_args()
    settings, Session = bootstrap()
    if args.once:
        db = Session()
        try:
            print(json.dumps(run_once(db, settings, include_all_companies=args.all), default=str))
        finally:
            db.close()
        return 0
    run_forever(Session, settings, include_all_companies=args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
