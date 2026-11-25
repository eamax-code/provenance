#!/usr/bin/env python
"""S-07: store each company's own fiscal year ends (the year each annual report covers).

python scripts/set_fiscal_year_ends.py --dry-run --out d.jsonl   # count, store nothing
python scripts/set_fiscal_year_ends.py                           # store

An annual report's own year is its annual period ending at the filing's period of report (the
SEC's report date, within 7 days), else its latest annual period (net income or revenue). Labels
then name a fiscal year by its own end date and a quarter by the own year end containing it, and
annual statement columns are these years only: other 12-month periods in a report (AAR's
November and June periods, Eros' September) are never columns. The dry run counts the annual
columns that would no longer show.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

from _bootstrap import bootstrap
from sqlalchemy import text, update

from app.db.models import Company
from app.services import periods

FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT", "10-KT/A")
NEAR = 7


def own_year_ends(db) -> dict[str, list]:
    """{cik: [own year end dates, oldest first]}"""
    rows = db.execute(text("""
        select f.cik, f.accession_number, f.period_end, fl.report_date
        from financial_facts f left join filings fl on fl.accession_number = f.accession_number
        where f.period_class = 'annual' and f.quality_status in ('ok', 'partial')
          and f.metric in ('net_income', 'revenue') and f.form_type = any(:forms)
        group by f.cik, f.accession_number, f.period_end, fl.report_date"""),
        {"forms": list(FORMS)}).all()  # fmt: skip
    by_filing: dict[tuple, list] = defaultdict(list)
    report: dict[tuple, object] = {}
    for cik, acc, end, rep in rows:
        by_filing[(cik, acc)].append(end)
        report[(cik, acc)] = rep
    out: dict[str, set] = defaultdict(set)
    for key, ends in by_filing.items():
        rep = report[key]
        near = [e for e in ends if rep and abs((e - rep).days) <= NEAR]
        out[key[0]].add(max(near) if near else max(ends))
    result = {}
    for cik, ends in out.items():
        kept: list = []
        for e in sorted(ends):  # one per year: a 52/53-week year can move by a few days
            if kept and (e - kept[-1]).days <= NEAR:
                kept[-1] = e
            else:
                kept.append(e)
        result[cik] = kept
    return result


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
    for cik, end in rows:
        if not periods.is_fiscal_year_end(end, tuple(own.get(cik) or ())):
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
    own = own_year_ends(db)
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
