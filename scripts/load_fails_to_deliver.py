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
from pathlib import Path

from _bootstrap import bootstrap

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
    folder = Path(settings.sec_bulk_dir) / "fails_to_deliver"
    out = open(args.out, "w") if args.out else None
    stats = ftd.load_new(
        db,
        sec,
        folder,
        reload=args.reload,
        limit=args.limit,
        write=not args.dry_run,
        on_file=(lambda r: out.write(json.dumps(r) + "\n")) if out else None,
    )
    if out:
        out.close()
    sec.close()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
