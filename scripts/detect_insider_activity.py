#!/usr/bin/env python
"""Find insider activity (launch plan F-03) in the loaded Forms 3, 4 and 5, as backfill.

  python scripts/detect_insider_activity.py            # every issuer with insider data
  python scripts/detect_insider_activity.py --cik 320193

Backfill never notifies: activity found here stays off the feed and webhooks. New activity is
found by the hourly filings tracker as Forms 4 arrive.
"""

from __future__ import annotations

import argparse
import json
import time

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import InsiderFiling
from app.services import insider_activity
from app.services.sec_client import normalize_cik


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cik", action="append", default=[])
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    ciks = [normalize_cik(c) for c in args.cik] or list(
        db.scalars(select(InsiderFiling.issuer_cik).distinct())
    )
    start = insider_activity.coverage_start(db)
    t, found = time.perf_counter(), {}
    for i, cik in enumerate(ciks, 1):
        for row in insider_activity.store(db, cik, None, start):
            found[row.activity_type] = found.get(row.activity_type, 0) + 1
        if i % 500 == 0:
            db.commit()
            print(json.dumps({"issuers": i, "of": len(ciks), "found": found}), flush=True)
    db.commit()
    print(json.dumps({"issuers": len(ciks), "found": found,
                      "seconds": round(time.perf_counter() - t, 1)}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
