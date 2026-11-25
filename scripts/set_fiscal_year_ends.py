#!/usr/bin/env python
"""S-07: store each company's own fiscal year ends (the year each annual report covers).

python scripts/set_fiscal_year_ends.py --dry-run --out d.jsonl   # count, store nothing
python scripts/set_fiscal_year_ends.py                           # store

Own years are read by app.services.fiscal_years: an annual report's own year (its period of
report, else its latest annual period) and its comparative years ending on the same day. Labels
then name a fiscal year by its own end date and a quarter by the own year end containing it, and
annual statement columns are these years only: other 12-month periods in a report (AAR's
November and June periods, Eros' September) are never columns. The dry run counts the annual
columns that would no longer show.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import text, update

from app.db.models import Company
from app.services import fiscal_years, periods

REMOVED: dict[str, list] = {}


def removed_columns(db, own: dict[str, list]) -> Counter:
    """Annual statement periods that are not a company's own fiscal year."""
    rows = db.execute(
        text("""
        select distinct cik, period_end from financial_facts
        where period_class = 'annual' and quality_status in ('ok', 'partial')
          and metric <> all(:cover)"""),
        {"cover": ["shares_outstanding", "public_float"]},
    ).all()
    c: Counter = Counter()
    t_ends = {k: {x[1] for x in v} for k, v in fiscal_years.transitions(db).items()}
    for cik, end in rows:
        if not periods.is_fiscal_year_end(end, tuple(own.get(cik) or ())) and not any(
                abs((end - t).days) <= 7 for t in t_ends.get(cik, ())):  # fmt: skip
            c[cik] += 1
            REMOVED.setdefault(cik, []).append(end.isoformat())
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    own = fiscal_years.own_year_ends(db)
    gone = removed_columns(db, own)
    stats = {"companies": len(own), "year_ends": sum(len(v) for v in own.values()),
             "columns_removed": sum(gone.values()),
             "companies_losing_columns": len(gone)}  # fmt: skip
    if args.out:
        with open(args.out, "w") as out:
            for cik, ends in sorted(own.items()):
                out.write(json.dumps({"cik": cik, "ends": [e.isoformat() for e in ends],
                                      "columns_removed": gone.get(cik, 0),
                                      "removed": sorted(REMOVED.get(cik, []))}) + "\n")  # fmt: skip
    if not args.dry_run:
        db.execute(update(Company).values(fiscal_year_ends=None))
        for cik, ends in own.items():
            db.execute(update(Company).where(Company.cik == cik).values(
                fiscal_year_ends=",".join(e.isoformat() for e in ends)))  # fmt: skip
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
