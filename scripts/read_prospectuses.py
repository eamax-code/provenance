#!/usr/bin/env python
"""Read the latest S-1/F-1 prospectus of companies going public, ahead of time.

  python scripts/read_prospectuses.py --cik 2130357
  python scripts/read_prospectuses.py --recent-days 90   # everyone who filed one lately

Each document is fetched from EDGAR once (needs SEC_USER_AGENT), cut into its main sections
and stored, so the chat (including the public demo key, which never fetches) can quote it.
Already-read documents are skipped.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Filing
from app.services import prospectus
from app.services.sec_client import SecClient, normalize_cik


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--recent-days", type=int, default=0, help="Filed one in the last N days")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    ciks = [normalize_cik(c) for c in args.cik]
    if args.recent_days:
        since = date.today() - timedelta(days=args.recent_days)
        ciks += [
            c
            for c in db.scalars(
                select(Filing.cik)
                .where(Filing.form_type.in_(prospectus.FORMS), Filing.filing_date >= since)
                .distinct()
            )
            if c not in ciks
        ]
    sec = SecClient(settings)
    total = {"companies": len(ciks), "read": 0, "stored": 0, "failed": 0, "none": 0}
    try:
        for cik in ciks:
            f = prospectus.latest_registration(db, cik)
            if f is None:
                total["none"] += 1
                continue
            total[prospectus.ensure_read(db, f, sec)] += 1
    finally:
        sec.close()
        db.close()
    print(json.dumps(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
