#!/usr/bin/env python
"""Successor registrants (launch plan K-05): a company continuing under a new holding company.

  python scripts/detect_successions.py --dry-run --years 10   # list, store nothing
  python scripts/detect_successions.py                        # store every pair found

See app/services/successions.py for the rules (an 8-K12B or 8-K12G3 by the successor, a Form
25/15 or 8-K item 3.01/3.03/2.01 by the predecessor around the same day, the same name once
legal-form words are removed, exactly one candidate).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import MartCompany
from app.services import successions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--years", type=float, default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    since = date.today() - timedelta(days=int(args.years * 365)) if args.years else None
    pairs = successions.detect(db, since)
    revenue = dict(db.execute(select(MartCompany.cik, MartCompany.latest_revenue)).all())

    def rev(p):
        return float(revenue.get(p["successor_cik"]) or revenue.get(p["predecessor_cik"]) or 0)

    for p in sorted(pairs, key=rev, reverse=True):
        print(json.dumps({**p, "effective_date": p["effective_date"].isoformat(),
                          "latest_revenue": rev(p) or None}))  # fmt: skip
    stored = 0 if args.dry_run else successions.store(db, pairs)
    print(json.dumps({"pairs": len(pairs), "stored_new": stored}))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
