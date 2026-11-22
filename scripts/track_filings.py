#!/usr/bin/env python
"""Read EDGAR's new filings once: refresh covered companies, add companies going public (ADR 0012).

  python scripts/track_filings.py              # one run, as the poller does every hour
  python scripts/track_filings.py --days 7     # also reread the last 7 days of daily indexes
  python scripts/track_filings.py --status     # what the tracker has seen and done

Needs SEC_USER_AGENT. The poller runs this every FILINGS_TRACKER_INTERVAL_SECONDS (an hour);
use the script for a first catch-up, from a platform cron, or after downtime.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta

from _bootstrap import bootstrap

from app.db.models import JobState, utcnow
from app.jobs import filings_tracker as job
from app.jobs.poll_sec import single_run_guard
from app.services import filings_tracker


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=0, help="Reread this many days of indexes")
    parser.add_argument("--max-companies", type=int, default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    settings, session_maker = bootstrap()
    db = session_maker()
    try:
        if args.status:
            print(json.dumps(filings_tracker.status(db), default=str, indent=2))
            return 0
        if args.days:
            day = (utcnow().astimezone(filings_tracker.EASTERN).date()
                   - timedelta(days=args.days + 1)).isoformat()  # fmt: skip
            state = db.get(JobState, filings_tracker.DAILY_STATE)
            if state is None:
                db.add(JobState(name=filings_tracker.DAILY_STATE, value=day))
            else:
                state.value = day
            db.commit()
        if args.max_companies:
            settings = settings.model_copy(
                update={"filings_tracker_max_companies": args.max_companies}
            )
        with single_run_guard(db, lock_file=settings.tracker_lock_file) as acquired:
            if not acquired:  # the poller or another run holds it
                print(json.dumps({"skipped": "another run is in progress"}))
                return 0
            summary = job.run(db, settings)
        print(json.dumps(summary, default=str, indent=2))
        return 0 if not summary.get("failed") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
