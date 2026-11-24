#!/usr/bin/env python
"""F-03c: correct stored insider activity events for the 4/A-aware rules (049fef3).

  python scripts/correct_insider_activity.py --out actions.jsonl     # dry run: counts, no writes
  python scripts/correct_insider_activity.py --write                 # retract, update, add

Only issuers with a Form 4/A carrying open-market lines can change. Events are never deleted:
retracted ones keep a reason, corrected ones what they said before (previous_values), new ones
are backfill (skipped, never notified).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import InsiderFiling, InsiderTransaction
from app.services import insider_activity


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default=None, help="the actions as JSONL")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    ciks = sorted(set(db.scalars(
        select(InsiderFiling.issuer_cik).join(
            InsiderTransaction,
            InsiderTransaction.accession_number == InsiderFiling.accession_number)
        .where(InsiderFiling.form_type == "4/A", InsiderTransaction.trans_code.in_(("P", "S")),
               InsiderTransaction.is_derivative.is_(False)))))  # fmt: skip
    start = insider_activity.coverage_start(db)
    counts: Counter = Counter()
    out = open(args.out, "w") if args.out else None
    for i, cik in enumerate(ciks, 1):
        for a in insider_activity.reconcile(db, cik, start, write=args.write):
            counts[(a["action"], a["key"][0].split(".")[-1], a.get("reason", ""))] += 1
            if out:
                row = {"cik": cik, "action": a["action"], "type": a["key"][0],
                       "accession_number": a["key"][1], "reason": a.get("reason"),
                       "old": a.get("old"), "new": a.get("new")}  # fmt: skip
                out.write(json.dumps(row) + "\n")
        if args.write:
            db.commit()
        if i % 250 == 0:
            print(json.dumps({"issuers": i, "of": len(ciks)}), flush=True)
    if out:
        out.close()
    print(json.dumps({"issuers": len(ciks), "write": args.write,
                      "actions": {" | ".join(k).strip(" |"): v
                                  for k, v in sorted(counts.items())}}, indent=1))  # fmt: skip
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
