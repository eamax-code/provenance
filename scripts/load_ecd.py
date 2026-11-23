#!/usr/bin/env python
"""Executive pay (D-10) and trading plans (D-11) from the ecd tags in the SEC's Financial
Statement and Notes data sets.

  python scripts/load_ecd.py .sec_bulk/fsn --from 2022q4 --dry-run --sample 30 > sample.json
  python scripts/load_ecd.py .sec_bulk/fsn --from 2022q4

Pay-versus-performance tables start with the 2023 proxies and trading-plan tags with periods
ending after mid-2023, so earlier data sets add nothing. Loading a set again replaces the rows
of every filing in it. After a write, trading-plan events are emitted (backfill never alerts).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from _bootstrap import bootstrap

from app.services import ecd


def _key(p: Path) -> str:
    stem = p.name.removesuffix("_notes.zip")  # 2024q1 or 2024_08
    y, rest = stem[:4], stem[5:] if "_" in stem else stem[4:]
    return f"{y}-{rest}" if rest.startswith("q") else f"{y}-q{(int(rest) - 1) // 3 + 1}m{rest}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("--from", dest="start", default="2022q4", help="first data set, e.g. 2022q4")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="with --dry-run: print N random rows")
    ap.add_argument("--seed", type=int, default=24)
    args = ap.parse_args()
    first = _key(Path(f"{args.start[:4]}_{args.start[4:]}_notes.zip")
                 if "q" not in args.start else Path(f"{args.start}_notes.zip"))  # fmt: skip
    files = [p for p in sorted(Path(args.folder).glob("*_notes.zip")) if _key(p) >= first]
    _, Session = bootstrap()
    if args.dry_run:
        plans, pays = [], []
        for p in files:
            pay, pl, stats = ecd.parse_notes_zip(p)
            plans += pl
            pays += pay
            print(json.dumps({"file": p.name, **stats}), flush=True)
        by_acc = {}
        for r in plans:
            by_acc[(r["accession_number"], r["member"], r["action"])] = r
        print(
            json.dumps(
                {
                    "plan_rows_unique": len(by_acc),
                    "pay_facts": len(pays),
                    "undated": sum(1 for r in by_acc.values() if not r["plan_date"]),
                }
            )
        )
        if args.sample:
            random.seed(args.seed)
            pick = random.sample(sorted(by_acc.values(), key=lambda r: (r["accession_number"],
                                                                        r["member"])),
                                 args.sample)  # fmt: skip
            print(json.dumps(pick, default=str, indent=1))
        return 0
    db = Session()
    for p in files:
        print(json.dumps({"file": p.name, **ecd.load(db, p)}), flush=True)
    from app.services import insider_plans, notifications

    events = insider_plans.emit_plan_events(db)
    alerts = notifications.create_dated_deliveries(db, events)
    db.commit()
    print(json.dumps({"trading_plan_events": len(events), "alerts": alerts}))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
