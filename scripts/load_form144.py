#!/usr/bin/env python
"""D-12: Form 144 notices of proposed sale, read through the SEC client (docs/contracts/
insider-plans.md).

  python scripts/load_form144.py --since 2025-11-24 --dry-run     # parse, store nothing
  python scripts/load_form144.py --since 2025-11-24               # store, then emit events

Reads each notice's raw XML (the Archives copy; cached documents cost no request), stores the
fields as given and emits sec.proposed_sale events (backfill never alerts; ADR 0004). The Form 4
that followed is joined at read time.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from _bootstrap import bootstrap

from app.services import form144
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", required=True, type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    stats = form144.load(db, sec, args.since, write=not args.dry_run, limit=args.limit)
    rows = stats.pop("rows") or []
    print(json.dumps({**stats, "parsed": len(rows) if args.dry_run else stats["stored"]}),
          flush=True)  # fmt: skip
    if not args.dry_run:
        from app.services import notifications

        events = form144.emit_events(db)
        alerts = notifications.create_dated_deliveries(db, events)
        db.commit()
        print(json.dumps({"proposed_sale_events": len(events), "alerts": alerts}))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
