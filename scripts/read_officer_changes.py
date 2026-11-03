#!/usr/bin/env python
"""Read officer and director changes from recent 8-K item 5.02 filings ahead of time.

  python scripts/read_officer_changes.py --cik 320193 --cik 789019
  python scripts/read_officer_changes.py --tickers   # every company with a ticker (slow)

Each filing is fetched from EDGAR once (needs SEC_USER_AGENT) and read by the local model
(LLM_ENABLED=true). Already-read filings are skipped, so re-running only reads new ones.
"""

from __future__ import annotations

import argparse
import json

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Company
from app.services import intel, officer_changes
from app.services.llm import LocalLLM
from app.services.sec_client import SecClient, normalize_cik


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--tickers", action="store_true", help="All companies with a ticker")
    parser.add_argument("--per-company", type=int, default=5)
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    ciks = [normalize_cik(c) for c in args.cik]
    if args.tickers:
        ciks += list(db.scalars(select(Company.cik).where(Company.ticker.is_not(None))))
    sec, llm = SecClient(settings), LocalLLM(settings)
    total = {"companies": 0, "fetched": 0, "extracted": 0, "failed": 0}
    try:
        for cik in ciks:
            filings = intel.leadership_filings(db, cik, None, limit=args.per_company)
            out = officer_changes.ensure_extracted(db, filings, sec=sec, llm=llm)
            total["companies"] += 1
            for k, v in out.items():
                total[k] += v
    finally:
        sec.close()
        db.close()
    print(json.dumps(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
