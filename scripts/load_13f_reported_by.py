#!/usr/bin/env python
"""Q-02: store the other managers each 13F names as reporting for it (13F notices).

  python scripts/load_13f_reported_by.py --dry-run     # counts and the Vanguard Group rows
  python scripts/load_13f_reported_by.py               # store (replaces what is there)

Reads the Form 13F data sets in SEC_BULK_DIR/13f and the EDGAR-loaded 13F notices from the
document cache only (a filing not cached is counted, never fetched).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import delete, insert, select

from app.db.models import Filing13F, ThirteenFReportedBy
from app.services import thirteenf
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    stored = set(db.scalars(select(Filing13F.accession_number)))
    rows: list[dict] = []
    for path in sorted(Path(settings.sec_bulk_dir, "13f").glob("*_form13f.zip")):
        rows += [
            r for r in thirteenf.reported_by_from_dataset(path) if r["accession_number"] in stored
        ]
    edgar = db.execute(select(Filing13F.accession_number, Filing13F.filer_cik)
                       .where(Filing13F.source == "sec:13f-edgar")).all()  # fmt: skip
    not_cached = 0
    for acc, cik in edgar:
        cached = sec._cache_read(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}.txt")
        if not cached:
            not_cached += 1
            continue
        rows += thirteenf.reported_by_from_submission(cached["body"], acc)
    rows = list({(r["accession_number"], r["seq"]): r for r in rows}.values())
    vg = [r for r in rows if r["accession_number"].startswith("0000102909-")]
    stats = {"rows": len(rows), "filings": len({r["accession_number"] for r in rows}),
             "with_cik": sum(1 for r in rows if r["cik"]), "edgar_not_cached": not_cached,
             "vanguard_group": vg[:12]}  # fmt: skip
    if not args.dry_run:
        db.execute(delete(ThirteenFReportedBy))
        for i in range(0, len(rows), 20_000):
            db.execute(insert(ThirteenFReportedBy), rows[i : i + 20_000])
        db.commit()
    print(json.dumps(stats, default=str, indent=1))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
