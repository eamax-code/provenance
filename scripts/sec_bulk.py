#!/usr/bin/env python
"""Cover all public companies from the SEC nightly bulk archives.

  python scripts/sec_bulk.py --download                 # 2 SEC requests; needs SEC_USER_AGENT
  python scripts/sec_bulk.py --scope facts --dry-run    # how many filers would be ingested
  python scripts/sec_bulk.py --scope known              # companies seeded by import_tickers.py
  python scripts/sec_bulk.py --scope facts --limit 500  # first 500 XBRL filers
  python scripts/sec_bulk.py --scope ciks --cik 320193 --cik 789019
  python scripts/sec_bulk.py --submissions PATH --facts PATH  # use archives downloaded elsewhere

Archives default to SEC_BULK_DIR (submissions.zip, companyfacts.zip). Each is over a gigabyte;
check free disk space first. Ingestion is idempotent, so re-running after the next nightly
rebuild only adds what changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap

from app.services import sec_bulk
from app.services.sec_client import SecClientError


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add = parser.add_argument
    add("--download", action="store_true", help="Download or revalidate both archives first")
    add("--scope", choices=sec_bulk.SCOPES, default=None)
    add("--cik", action="append", default=[], help="With --scope ciks; repeatable")
    add("--limit", type=int, default=None)
    add("--dry-run", action="store_true", help="Only report how many CIKs would be ingested")
    add("--no-facts", action="store_true", help="Filings only")
    add("--submissions", type=Path, default=None)
    add("--facts", type=Path, default=None)
    args = parser.parse_args()
    settings, Session = bootstrap()
    base = Path(settings.sec_bulk_dir)
    subs = args.submissions or base / "submissions.zip"
    facts = args.facts or base / "companyfacts.zip"
    if args.download:
        try:
            out = sec_bulk.download_archives(settings)
        except (SecClientError, ValueError) as exc:
            print(f"download failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({k: {**v, "path": str(v["path"])} for k, v in out.items()}, default=str))
    if not args.scope:
        return 0
    if not subs.exists():
        print(f"{subs} not found; run with --download or pass --submissions", file=sys.stderr)
        return 2
    db = Session()
    try:
        if args.dry_run:
            client = sec_bulk.ArchiveClient(settings, subs, facts if facts.exists() else None)
            try:
                ciks = sec_bulk.select_ciks(db, client, args.scope, args.cik, args.limit)
            finally:
                client.close()
            print(json.dumps({"scope": args.scope, "would_ingest": len(ciks), "sample": ciks[:5]}))
            return 0
        summary = sec_bulk.bulk_ingest(
            db,
            settings,
            subs,
            facts if facts.exists() else None,
            scope=args.scope,
            ciks=args.cik,
            limit=args.limit,
            include_facts=not args.no_facts,
        )
        print(json.dumps(summary, default=str))
        return 0 if summary["failed"] == 0 else 3
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
