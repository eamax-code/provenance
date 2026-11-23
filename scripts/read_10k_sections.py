#!/usr/bin/env python
"""X-14: read Item 1A and Item 7 of the two latest 10-Ks for a set of companies, through the
SEC client, and store them as sections 10k:1A and 10k:7 (docs/contracts/changes.md).

  python scripts/read_10k_sections.py --ciks 320193,789019        # these companies
  python scripts/read_10k_sections.py --showcase --largest 300    # the read set

The read set is the showcase companies first, then the largest filers by latest annual revenue
(USD reporters with a 10-K in the last two years). A report already stored is not fetched again.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from _bootstrap import bootstrap
from sqlalchemy import select

from app.services import tenk_sections
from app.services.public import showcase_ciks
from app.services.sec_client import SecClient, SecClientError, normalize_cik


def largest(db, n: int) -> list[str]:
    from app.db.models import MartCompany

    since = date.today() - timedelta(days=730)
    return list(db.scalars(
        select(MartCompany.cik).where(
            MartCompany.latest_revenue.is_not(None), MartCompany.reporting_currency == "USD",
            MartCompany.latest_annual_report_form.in_(tenk_sections.FORMS),
            MartCompany.latest_annual_report_date >= since,
        ).order_by(MartCompany.latest_revenue.desc()).limit(n)
    ))  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ciks", default="")
    ap.add_argument("--showcase", action="store_true")
    ap.add_argument("--largest", type=int, default=0)
    ap.add_argument("--refresh", action="store_true", help="read stored reports again")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    ciks = [normalize_cik(c) for c in args.ciks.split(",") if c.strip()]
    if args.showcase:
        ciks += [c for c in showcase_ciks(db, settings)[0] if c not in ciks]
    if args.largest:
        ciks += [c for c in largest(db, args.largest) if c not in ciks]
    done = failed = 0
    for cik in ciks:
        for f in tenk_sections.annual_reports(db, cik, limit=2):
            try:
                res = tenk_sections.read_filing(db, sec, f, args.refresh)
                print(json.dumps({"cik": cik, **res}), flush=True)
                done += 1
            except SecClientError as exc:
                db.rollback()
                failed += 1
                print(json.dumps({"cik": cik, "accession_number": f.accession_number,
                                  "error": str(exc)[:200]}), flush=True)  # fmt: skip
    print(json.dumps({"companies": len(ciks), "reports": done, "failed": failed}))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
