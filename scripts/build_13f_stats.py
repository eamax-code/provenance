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

from app.services import fund_managers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quarter", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    quarters = [args.quarter] if args.quarter else None
    for row in fund_managers.rebuild(db, quarters, write=not args.dry_run):
        print(json.dumps(row), flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
