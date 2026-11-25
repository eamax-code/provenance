#!/usr/bin/env python
"""F-03f: mark the stored code-P lines bought under an employee or director stock purchase plan,
a plan trust or dividend reinvestment (insider_transactions.plan_purchase), from the SEC insider
data sets in SEC_BULK_DIR/insiders and, for Forms 4 read as filed, the document cache (no SEC
requests; a filing not cached is counted and left null).

  python scripts/flag_plan_purchases.py --dry-run --out plan.jsonl   # count, store nothing
  python scripts/flag_plan_purchases.py                              # store

Also sets plan_inferred (F-03g): a code-P line not stated as one whose shares are a fraction under
100. Then scripts/correct_insider_activity.py --change f03f, then --change f03g, retracts the
cluster and first-buy events that counted them (never deleted).
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import select, text

from app.db.models import Filing, InsiderTransaction
from app.services import insiders
from app.services.insider_screener import unquote
from app.services.sec_client import SecClient


def from_dataset(path: Path) -> dict[tuple, bool]:
    """{(accession, row key): plan purchase} for one quarter's code-P lines."""
    out: dict[tuple, bool] = {}
    with zipfile.ZipFile(path) as zf:
        notes = {
            (r["ACCESSION_NUMBER"].strip(), (r.get("FOOTNOTE_ID") or "").strip()): unquote(
                r.get("FOOTNOTE_TXT")
            )
            or ""
            for r in insiders._tsv(zf, "FOOTNOTES.TSV")
        }
        for r in insiders._tsv(zf, "NONDERIV_TRANS.TSV"):
            if (r.get("TRANS_CODE") or "").strip() != "P":
                continue
            acc = r["ACCESSION_NUMBER"].strip()
            mine = [
                notes.get((acc, i.strip()), "")
                for f in insiders.LINE_FN
                for i in (r.get(f) or "").split(",")
                if i.strip()
            ]
            out[(acc, (r.get("NONDERIV_TRANS_SK") or "").strip())] = bool(
                insiders.plan_purchase("P", r.get("NATURE_OF_OWNERSHIP"), mine)
            )
    return out  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    t = InsiderTransaction
    stored = {
        (a, k)
        for a, k in db.execute(
            select(t.accession_number, t.row_key).where(
                t.trans_code == "P", t.row_kind == "transaction", t.is_derivative.is_(False)
            )
        )
    }
    found: dict[tuple, bool] = {}
    for path in sorted(Path(settings.sec_bulk_dir, "insiders").glob("*_form345.zip")):
        found.update({k: v for k, v in from_dataset(path).items() if k in stored})
    stats: Counter = Counter()
    sec = SecClient(settings)
    for acc in sorted({a for a, k in stored if k.startswith("x")}):
        f = db.scalar(select(Filing).where(Filing.accession_number == acc))
        url = insiders._xml_url(f) if f is not None else None
        cached = sec._cache_read(url) if url else None  # the cache only: never a request
        if not cached or not cached.get("body"):
            stats["xml filings not cached"] += 1
            continue
        for r in insiders.parse_ownership_xml(cached["body"], acc, f.filing_date).rows:
            if (acc, r["row_key"]) in stored and r["plan_purchase"] is not None:
                found[(acc, r["row_key"])] = r["plan_purchase"]
    sec.close()
    stats.update({"P lines": len(stored), "read": len(found), "left null": len(stored) - len(found),
                  "plan purchases": sum(found.values())})  # fmt: skip
    if args.out:
        with open(args.out, "w") as out:
            for (a, k), v in sorted(found.items()):
                if v:
                    out.write(json.dumps({"accession_number": a, "row_key": k}) + "\n")
    if not args.dry_run:
        db.execute(text("create temporary table f03f (a varchar(25), k text, v boolean)"))
        rows = [{"a": a, "k": k, "v": v} for (a, k), v in found.items()]
        for i in range(0, len(rows), 5000):
            db.execute(text("insert into f03f values (:a, :k, :v)"), rows[i : i + 5000])
        stats["written"] = db.execute(
            text("""
            update insider_transactions t set plan_purchase = f.v from f03f f
            where t.accession_number = f.a and t.row_key = f.k and t.trans_code = 'P'
              and t.row_kind = 'transaction' and not t.is_derivative""")
        ).rowcount
        db.commit()
    # F-03g: a code-P line not stated as a plan purchase whose shares are a fraction under 100
    inferred = """not coalesce(plan_purchase, false) and shares < 100 and shares <> trunc(shares)"""
    where = "trans_code = 'P' and row_kind = 'transaction' and not is_derivative"
    stats["inferred (fractional under 100 shares)"] = db.execute(
        text(f"select count(*) from insider_transactions where {where} and {inferred}")
    ).scalar()
    if not args.dry_run:
        db.execute(
            text(
                f"update insider_transactions set plan_inferred = coalesce({inferred}, "
                f"false) where {where}"
            )
        )
        db.commit()
        # Q-03f: the screener's per-Form-4 groups carry the plan bucket: rebuild them
        from app.services import insider_screener

        insider_screener.refresh_groups(db)
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
