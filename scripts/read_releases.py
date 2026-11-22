#!/usr/bin/env python
"""First-reported dates from 8-K item 2.02 earnings releases (launch plan E-2).

  python scripts/read_releases.py --years 2 --min-revenue 1e9   # active $1B+ companies
  python scripts/read_releases.py --cik 320193 --years 5
  python scripts/read_releases.py --top 500 --releases 4         # batch 1: largest USD reporters

Reads each earnings release (exhibit 99.1) once (two SEC requests: the filing index and the
exhibit; needs SEC_USER_AGENT), stores its text like other filing text, then records each 10-Q
and 10-K figure the release stated with the same value (app.services.first_reported).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Filing, MartCompany
from app.services import first_reported, releases
from app.services.sec_client import SecClient, normalize_cik


def save_progress(db, key: str, value: dict) -> None:
    from app.db.models import JobState, utcnow

    row = db.get(JobState, key)
    text = json.dumps({**value, "at": utcnow().isoformat()})
    if row is None:
        db.add(JobState(name=key, value=text, updated_at=utcnow()))
    else:
        row.value, row.updated_at = text, utcnow()
    db.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cik", action="append", default=[])
    ap.add_argument("--years", type=float, default=2)
    ap.add_argument("--min-revenue", type=float, default=None)
    ap.add_argument("--no-fetch", action="store_true", help="Match stored releases only")
    ap.add_argument("--progress-key", default=None,
                    help="job_state name to record progress under (resumable: stored releases "
                    "are skipped, matching is idempotent)")  # fmt: skip
    ap.add_argument(
        "--top",
        type=int,
        default=None,
        help="The N active USD reporters with the largest latest revenue",
    )
    ap.add_argument("--releases", type=int, default=None,
                    help="Read only each company's latest N earnings releases")  # fmt: skip
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    since = date.today() - timedelta(days=int(args.years * 365))
    ciks = [normalize_cik(c) for c in args.cik]
    if args.min_revenue is not None:
        ciks += list(db.scalars(select(MartCompany.cik).where(
            MartCompany.latest_revenue >= args.min_revenue,
            MartCompany.reporting_currency == "USD",
            MartCompany.latest_annual_report_date >= date.today() - timedelta(days=730),
        )))  # fmt: skip
    if args.top:
        ciks += list(db.scalars(
            select(MartCompany.cik).where(
                MartCompany.reporting_currency == "USD", MartCompany.latest_revenue.is_not(None),
                MartCompany.latest_annual_report_date >= date.today() - timedelta(days=730),
            ).order_by(MartCompany.latest_revenue.desc()).limit(args.top)
        ))  # fmt: skip
    sec = None if args.no_fetch else SecClient(settings)
    out = {"companies": 0, "releases_read": 0, "figures_matched": 0}
    ciks = list(dict.fromkeys(ciks))
    for cik in ciks:
        todo = db.scalars(select(Filing).where(
            Filing.cik == cik, Filing.form_type.like("8-K%"),
            Filing.items.like(f"%{releases.EARNINGS_ITEM}%"), Filing.filing_date >= since,
        ).order_by(Filing.filing_date.desc()).limit(args.releases)).all()  # fmt: skip
        for f in todo:
            out["releases_read"] += releases.ensure_read(db, f, sec) == "read"
        out["figures_matched"] += first_reported.match_company(db, cik, since - timedelta(days=200))
        out["companies"] += 1
        if out["companies"] % 50 == 0:
            print(json.dumps(out), flush=True)
            if args.progress_key:
                save_progress(db, args.progress_key, {**out, "of": len(ciks)})
    print(json.dumps(out))
    if args.progress_key:
        save_progress(db, args.progress_key, {**out, "of": len(ciks), "done": True})
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
