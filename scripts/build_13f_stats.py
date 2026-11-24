#!/usr/bin/env python
"""Q-02: per-security 13F stats, the thousands-after-2023 check and the funds activity list.

  python scripts/build_13f_stats.py --dry-run          # counts only, store nothing
  python scripts/build_13f_stats.py                    # every quarter with full data loaded
  python scripts/build_13f_stats.py --quarter 2026-09-30

Run after each Form 13F load. Reads stored holdings only (no SEC requests).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import Filing13F
from app.services import fund_managers, thirteenf

FULL = 5000  # a quarter with fewer managers than this is not fully loaded


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quarter", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    managers = func.count(Filing13F.filer_cik.distinct())
    counts = dict(db.execute(select(Filing13F.report_period, managers)
                             .group_by(Filing13F.report_period)).all())  # fmt: skip
    quarters = [args.quarter] if args.quarter else sorted(q for q, n in counts.items() if n >= FULL)
    for q in quarters:
        print(json.dumps(fund_managers.build_stats(db, q, write=not args.dry_run)), flush=True)
        if counts.get(thirteenf.previous_quarter(q), 0) >= FULL:
            print(json.dumps(fund_managers.build_activity(db, q, write=not args.dry_run)),
                  flush=True)  # fmt: skip
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
