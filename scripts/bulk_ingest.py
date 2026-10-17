#!/usr/bin/env python
"""Seed the universe and/or run one budgeted bulk-ingestion pass (resumable).

Examples:
  python scripts/bulk_ingest.py --seed-file data/universe.sample.txt
  python scripts/bulk_ingest.py --seed-tickers --top 500
  python scripts/bulk_ingest.py --budget 400 --max-companies 150 --history-pages 1
  python scripts/bulk_ingest.py --status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import UniverseMember
from app.services import universe
from app.services.sec_client import SecClient, SecClientError


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add = parser.add_argument
    add("--seed-file", type=Path, help="Text file with one CIK per line")
    add("--seed-tickers", action="store_true", help="Seed from the SEC ticker/exchange file")
    add("--top", type=int, default=None, help="With --seed-tickers: only the first N issuers")
    add("--budget", type=int, default=None, help="Max SEC requests this run")
    add("--max-companies", type=int, default=None)
    add("--history-pages", type=int, default=None, help="Older-filings pages per company")
    add("--seed-only", action="store_true", help="Seed and exit without ingesting")
    add("--status", action="store_true", help="Print universe counts and exit")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    client = None
    try:
        if args.status:
            count = func.count(UniverseMember.id)
            total = db.scalar(select(count)) or 0
            active = db.scalar(select(count).where(UniverseMember.is_active.is_(True))) or 0
            succeeded = (
                db.scalar(select(count).where(UniverseMember.last_success_at.is_not(None))) or 0
            )
            status = {
                "members": total,
                "active": active,
                "ever_succeeded": succeeded,
                "due_now": universe.count_due(db),
            }
            print(json.dumps(status))
            return 0
        if args.seed_file:
            lines = args.seed_file.read_text().splitlines()
            stats = universe.seed_from_lines(db, lines, source="file")
            db.commit()
            print(f"seeded from file: {stats}")
        if args.seed_tickers:
            client = SecClient(settings)
            resp = client.fetch_ticker_exchange()
            stats = universe.seed_from_tickers(db, resp.data, top_n=args.top)
            db.commit()
            print(f"seeded from tickers: {stats}")
        if args.seed_only:
            return 0
        client = client or SecClient(settings)
        summary = universe.bulk_ingest(
            db,
            settings,
            client,
            request_budget=args.budget,
            max_companies=args.max_companies,
            history_pages=args.history_pages,
        )
        print(json.dumps(summary))
        return 0
    except SecClientError as exc:
        print(f"SEC request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
