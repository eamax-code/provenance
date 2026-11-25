#!/usr/bin/env python
"""S-06: flag EPS that does not reconcile with the same filing's net income over weighted shares.

python scripts/flag_eps_reconcile.py --dry-run --out found.jsonl   # count, store nothing
python scripts/flag_eps_reconcile.py                               # set quality_status

Within 5% of 100x: the EPS is "unit_doubtful" (probably cents or pence tagged as the main unit).
Within 5% of 1,000x or 1/100 (S-06b): the one figure the company's other filings show to be off
(EPS, net income or weighted shares) is "unit_doubtful". Values are never changed. The company
ingest applies the same check.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from _bootstrap import bootstrap

from app.services import eps_reconcile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    cents = eps_reconcile.find(db)
    off = eps_reconcile.find_off(db)
    found = cents + off
    stats = Counter(f"100x EPS: {f['metric']}" for f in cents)
    stats.update(f"off by a scale: {f['metric']} x{f['factor']:g}" for f in off)
    stats["companies"] = len({f["cik"] for f in found})
    stats["already flagged"] = sum(f["was"] in eps_reconcile.STATUSES for f in found)
    if args.out:
        with open(args.out, "w") as out:
            for f in found:
                out.write(json.dumps(f, default=str) + "\n")
    if not args.dry_run:
        stats["changed"] = eps_reconcile.apply(db, found=found)
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
