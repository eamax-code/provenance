#!/usr/bin/env python
"""Read IPO deal terms (launch plan F-02) for companies going public.

  python scripts/read_ipo_terms.py --days 90        # everyone with IPO activity lately
  python scripts/read_ipo_terms.py --cik 2130357    # one company

Fetches each final prospectus (424B4) and latest registration amendment once (needs
SEC_USER_AGENT), keeps its cover page and sections, and stores the terms with their evidence.
The hourly filings tracker does the same for new filings.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from _bootstrap import bootstrap

from app.services import ipo_pipeline, ipo_terms
from app.services.sec_client import SecClient, normalize_cik


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cik", action="append", default=[])
    ap.add_argument("--days", type=int, default=0)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    ciks = [normalize_cik(c) for c in args.cik]
    if args.days:
        since = date.today() - timedelta(days=args.days)
        ciks += [i["cik"] for i in ipo_pipeline.companies(db, since) if i["kind"] == "ipo"]
    sec = SecClient(settings)
    done = {cik: ipo_terms.read_company(db, cik, sec) for cik in dict.fromkeys(ciks)}
    print(json.dumps({"companies": len(done), "documents": sum(done.values())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
