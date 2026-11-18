#!/usr/bin/env python
"""Load the sources of the connections graph (ADR 0011).

  python scripts/ingest_connections.py --insider-quarters 12      # latest 12 quarterly data sets
  python scripts/ingest_connections.py --quarter 2025q3            # one data set
  python scripts/ingest_connections.py --showcase                  # exhibit 21, 13D/G, recent 3/4/5
  python scripts/ingest_connections.py --cik 320193 --cik 789019

The insider data sets (every Form 3, 4 and 5 of a quarter, about 8 MB each) are downloaded into
SEC_BULK_DIR/insiders and loaded for all issuers; a quarter already loaded with the same file is
skipped. Per-company sources are read from EDGAR (needs SEC_USER_AGENT); the API also reads them
on demand for keyed callers, never for the demo key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.api.routes_graph import refresh_sources
from app.services import insiders
from app.services.public import showcase_ciks
from app.services.sec_client import SecClient, normalize_cik


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insider-quarters", type=int, default=0, help="Latest N data sets")
    parser.add_argument("--quarter", action="append", default=[], help="e.g. 2025q3")
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--showcase", action="store_true", help="The public showcase companies")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    out: dict = {"datasets": [], "companies": []}
    try:
        if args.insider_quarters or args.quarter:
            available = insiders.discover_datasets(sec)
            wanted = list(available)[-args.insider_quarters :] if args.insider_quarters else []
            wanted += [q for q in args.quarter if q in available and q not in wanted]
            folder = Path(settings.sec_bulk_dir) / "insiders"
            folder.mkdir(parents=True, exist_ok=True)
            for q in wanted:
                dest = folder / f"{q}_form345.zip"
                sec.download_file(available[q], dest)
                out["datasets"].append(insiders.load_dataset(db, dest, q))
                print(json.dumps(out["datasets"][-1], default=str), flush=True)
        ciks = [normalize_cik(c) for c in args.cik]
        if args.showcase:
            ciks += [c for c in showcase_ciks(db, settings)[0] if c not in ciks]
        for cik in ciks:
            res = refresh_sources(db, sec, cik)
            out["companies"].append(res)
            print(json.dumps(res, default=str), flush=True)
    finally:
        sec.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
