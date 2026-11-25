#!/usr/bin/env python
"""Q-03f: rebuild insider_form4_groups (the insider screener's per-Form-4 groups) from the lines.

Run after migration e4a6c8b0d2f5 and after any bulk change to insider lines outside
insiders.store (scripts/flag_plan_purchases.py runs it). About a minute; no SEC requests.

  python scripts/build_insider_groups.py
"""

from __future__ import annotations

import json
import sys
import time

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import InsiderForm4Group
from app.services import insider_screener


def main() -> int:
    _, Session = bootstrap()
    db = Session()
    t0 = time.perf_counter()
    insider_screener.refresh_groups(db)
    db.commit()
    n = db.scalar(select(func.count()).select_from(InsiderForm4Group))
    print(json.dumps({"groups": n, "fresh": insider_screener.groups_fresh(db),
                      "seconds": round(time.perf_counter() - t0, 1)}))  # fmt: skip
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
