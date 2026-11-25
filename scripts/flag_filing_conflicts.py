#!/usr/bin/env python
"""M-01: mark the figures a filing reports twice for one period (IFRS beside US GAAP) that the
company's other filings do not back.

python scripts/flag_filing_conflicts.py --dry-run --out found.jsonl   # count, store nothing
python scripts/flag_filing_conflicts.py                               # set quality_status

The figure the company's other filings agree with (within half a percent) stays; the other is
"ambiguous_mapping". When none agrees, all are, and statements show no figure for that cell,
with a note. Values are never changed. The company ingest applies the same check.
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap

from app.services import filing_conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    found = filing_conflicts.find(db)
    stats = {"conflicts": len(found), "companies": len({c["cik"] for c in found}),
             "none_backed": sum(c["none"] for c in found),
             "to_mark": len({i for c in found for i in c["drop"]})}  # fmt: skip
    if args.out:
        with open(args.out, "w") as out:
            for c in found:
                out.write(json.dumps({**c, "drop": [str(i) for i in c["drop"]],
                                      "was": {str(k): v for k, v in c["was"].items()}},
                                     default=str) + "\n")  # fmt: skip
    if not args.dry_run:
        stats["changed"] = filing_conflicts.apply(db, found=found)
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
