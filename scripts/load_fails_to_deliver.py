#!/usr/bin/env python
"""Q-06: load the SEC's fails-to-deliver half-month files (from July 2009) into fails_to_deliver,
for CUSIPs mapped to a company here, through SecClient (8 requests a second or fewer, cached,
stopping on 403 or 429). A file already loaded is skipped unless --reload.

  python scripts/load_fails_to_deliver.py --dry-run --out files.jsonl   # count, store nothing
  python scripts/load_fails_to_deliver.py                               # store
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import FtdFile
from app.services import fails_to_deliver as ftd
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="per-file counts (JSONL)")
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="at most this many files")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    files = ftd.discover(sec.get_text(ftd.PAGE).data)
    have = set(db.scalars(select(FtdFile.name)))
    todo = [n for n in files if args.reload or n not in have][: args.limit]
    folder = Path(settings.sec_bulk_dir) / "fails_to_deliver"
    stats: Counter = Counter(files_listed=len(files), files_to_load=len(todo))
    out = open(args.out, "w") if args.out else None
    for i, name in enumerate(todo, 1):
        data, published = ftd.fetch(sec, name, files[name], folder)
        got = ftd.store(db, name, ftd.parse(data), published, write=not args.dry_run)
        if not args.dry_run:
            db.commit()
        stats["rows"] += got["rows"]
        stats["matched"] += got["matched"]
        if out:
            out.write(json.dumps({**got, "published": published.isoformat()}) + "\n")
        if i % 25 == 0:
            print(json.dumps({"files": i, **stats}), flush=True)
    if out:
        out.close()
    sec.close()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
