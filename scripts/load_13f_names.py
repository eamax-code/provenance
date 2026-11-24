#!/usr/bin/env python
"""Q-02: store the issuer name most managers gave each security on Form 13F, per quarter.

  python scripts/load_13f_names.py --dry-run --out names.jsonl   # count and write, store nothing
  python scripts/load_13f_names.py                               # store (replaces those quarters)

Reads the Form 13F data sets in SEC_BULK_DIR/13f and, for quarters loaded from EDGAR one filing
at a time, each stored filing's submission from the document cache only (a filing not cached is
counted, never fetched). The CUSIP stays internal: it keys the name, it is never returned.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import delete, insert, select

from app.db.models import Filing13F, ThirteenFIssuerName
from app.services import thirteenf
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="with --dry-run: write the rows here (JSONL)")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    out: dict = {}
    stats: dict = {"datasets": 0, "dataset_rows": 0, "edgar_filings": 0, "edgar_rows": 0,
                   "edgar_not_cached": 0}  # fmt: skip
    for path in sorted(Path(settings.sec_bulk_dir, "13f").glob("*_form13f.zip")):
        stats["dataset_rows"] += thirteenf.names_from_dataset(path, out)
        stats["datasets"] += 1
        print(json.dumps({"dataset": path.name, "keys": len(out)}), flush=True)
    edgar = db.execute(select(Filing13F.accession_number, Filing13F.filer_cik,
                              Filing13F.report_period)
                       .where(Filing13F.source == "sec:13f-edgar",
                              Filing13F.form_type.in_(thirteenf.HOLDINGS_FORMS))).all()  # fmt: skip
    for acc, cik, period in edgar:
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}.txt"
        cached = sec._cache_read(url)
        if not cached:
            stats["edgar_not_cached"] += 1
            continue
        stats["edgar_rows"] += thirteenf.names_from_submission(cached["body"], acc, period, out)
        stats["edgar_filings"] += 1
    rows = thirteenf.name_rows(out)
    stats["names"] = len(rows)
    stats["quarters"] = sorted({str(r["report_period"]) for r in rows})[-6:]
    if args.dry_run:
        if args.out:
            with open(args.out, "w") as f:
                for r in rows:
                    f.write(json.dumps(r, default=str) + "\n")
        print(json.dumps(stats))
        return 0
    periods = sorted({r["report_period"] for r in rows})
    db.execute(delete(ThirteenFIssuerName).where(ThirteenFIssuerName.report_period.in_(periods)))
    for i in range(0, len(rows), 20_000):
        db.execute(insert(ThirteenFIssuerName), rows[i : i + 20_000])
    db.commit()
    print(json.dumps({**stats, "stored": len(rows)}))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
