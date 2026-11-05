"""Rebuild the quick-answer marts (issue #8).

python scripts/build_marts.py                 # every company and the filing activity
python scripts/build_marts.py --cik 320193    # one or more companies only
"""

from __future__ import annotations

import argparse
import time

from _bootstrap import bootstrap

from app.services import marts
from app.services.sec_client import normalize_cik


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cik", action="append", help="Rebuild only this company (repeatable)")
    args = parser.parse_args()
    _, Session = bootstrap()
    db = Session()
    try:
        ciks = [normalize_cik(c) for c in args.cik] if args.cik else None
        t = time.perf_counter()
        n = marts.build_company_marts(db, ciks)
        print(f"mart_company: {n} rows in {time.perf_counter() - t:.1f}s")
        t = time.perf_counter()
        n, years = marts.build_financial_marts(db, ciks)
        print(
            f"mart_financials: {n} rows, mart_company_period: {years} rows in "
            f"{time.perf_counter() - t:.1f}s"
        )
        if not ciks:
            t = time.perf_counter()
            n = marts.build_filing_activity(db)
            print(f"mart_filing_activity: {n} rows in {time.perf_counter() - t:.1f}s")
    finally:
        db.close()


if __name__ == "__main__":
    main()
