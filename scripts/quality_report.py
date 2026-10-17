#!/usr/bin/env python
"""Print the latest data-quality snapshot and a short trend.

Usage: python scripts/quality_report.py [--limit 10] [--take]
(--take records a new snapshot first)
"""

from __future__ import annotations

import argparse
import sys

from _bootstrap import bootstrap

from app.services import quality


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--take", action="store_true", help="Take a fresh snapshot before printing")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    try:
        if args.take:
            quality.take_snapshot(db, settings)
            db.commit()
        print(quality.render_report(db, limit=args.limit))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
