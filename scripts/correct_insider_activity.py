#!/usr/bin/env python
"""Correct stored insider activity events after a rule change, as corrections.

  python scripts/correct_insider_activity.py --out actions.jsonl     # dry run: counts, no writes
  python scripts/correct_insider_activity.py --write                 # retract, update, add
  python scripts/correct_insider_activity.py --change f03b           # joint filers as one buyer

--change f03d: affiliates that file apart (F-03d) are one buyer. --change f03f: a purchase
under an employee or director stock purchase plan, a plan trust or dividend reinvestment is not
an open-market buy (only issuers with such a line can change). --change f03g: nor is one likely
under a plan though not stated (a fraction of a share under 100 shares). --change f03c
(default): the 4/A-aware rules (049fef3); only issuers with a Form 4/A carrying
open-market lines can change. --change f03b: joint filers count as one buyer for cluster buying;
only issuers with a stored cluster event can change. Events are never deleted:
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

from app.db.models import InsiderActivity, InsiderFiling, InsiderTransaction
from app.services import insider_activity

JOINT = (
    "joint filers counted as separate buyers: the reporting owners of one Form 4, and "
    "entities that file together, are one buyer"
)


AFFILIATES = (
    "affiliates counted as separate buyers: a fund group whose entities file apart, or "
    "the individual who controls it, is one buyer"
)


INFERRED = "inferred plan purchase (a fractional purchase under 100 shares)"


PLAN = (
    "a plan purchase counted as an open-market buy: shares bought under an employee or "
    "director stock purchase plan, a plan trust or dividend reinvestment"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default=None, help="the actions as JSONL")
    ap.add_argument("--change", choices=("f03c", "f03b", "f03d", "f03f", "f03g"),
                    default="f03c")  # fmt: skip
    ap.add_argument("--no-add", action="store_true", help="retract and update only (F-03b)")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    rules = {"f03c": None, "f03b": {"joint_as_one": False},
             "f03d": {"affiliated": False}, "f03f": {"plan": False},
             "f03g": {"inferred": False}}[args.change]  # fmt: skip
    ciks = sorted(set(db.scalars(select(InsiderTransaction.issuer_cik).where(
        InsiderTransaction.plan_purchase.is_(True))))) if args.change == "f03f" else \
        sorted(set(db.scalars(select(InsiderTransaction.issuer_cik).where(
            InsiderTransaction.plan_inferred.is_(True))))) if args.change == "f03g" else \
        sorted(set(db.scalars(select(InsiderActivity.cik).where(
        InsiderActivity.activity_type == insider_activity.CLUSTER)))) if rules else \
        sorted(set(db.scalars(
        select(InsiderFiling.issuer_cik).join(
            InsiderTransaction,
            InsiderTransaction.accession_number == InsiderFiling.accession_number)
        .where(InsiderFiling.form_type == "4/A", InsiderTransaction.trans_code.in_(("P", "S")),
               InsiderTransaction.is_derivative.is_(False)))))  # fmt: skip
    start = insider_activity.coverage_start(db)
    counts: Counter = Counter()
    out = open(args.out, "w") if args.out else None
    for i, cik in enumerate(ciks, 1):
        for a in insider_activity.reconcile(
            db,
            cik,
            start,
            write=args.write,
            before_rules=rules,
            reason={"f03b": JOINT, "f03d": AFFILIATES, "f03f": PLAN, "f03g": INFERRED}.get(
                args.change
            ),  # fmt: skip
            adds=not args.no_add,
        ):
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
