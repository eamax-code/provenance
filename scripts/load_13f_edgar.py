#!/usr/bin/env python
"""Form 13F filings from EDGAR one by one (launch plan E-1b), for filings the data sets do not
cover yet (resumable; one request per filing through the shared SEC limit).

  python scripts/load_13f_edgar.py --after 2026-08-31 --quarter 2026Q3 --quarter 2026Q4

The loaded-through date (which decides the latest complete quarter shown) moves to the latest
filing date only when every listed filing was read; rerun to finish failed ones first.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from _bootstrap import bootstrap

from app.services import thirteenf, thirteenf_edgar
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--after",
        type=date.fromisoformat,
        required=True,
        help="Read filings filed after this date (the data sets cover up to it)",
    )
    ap.add_argument("--quarter", action="append", required=True, help="e.g. 2026Q4")
    args = ap.parse_args()  # fmt: skip
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    items: list[dict] = []
    for q in args.quarter:
        year, quarter = int(q[:4]), int(q[-1])
        text = sec.get_text(thirteenf_edgar.index_url(year, quarter)).data
        items += thirteenf_edgar.list_filings(text, args.after)
    out = thirteenf_edgar.load(db, sec, items, progress=lambda p: print(json.dumps(p), flush=True))
    if out["complete"] and items:
        through = max(i["filed"] for i in items)
        thirteenf.mark_loaded_through(db, through)
        db.commit()
        out["loaded_through"] = through.isoformat()
    print(json.dumps(out, default=str))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
