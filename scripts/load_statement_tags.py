#!/usr/bin/env python
"""Income-statement revenue lines per filing, from the Notes data sets (mapping 1.5.0).
  python scripts/load_statement_tags.py .sec_bulk/fsn
Reads pre.tsv in every *_notes.zip in the folder (local files, no SEC requests); a reload
replaces each filing's rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.services import statement_tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    total = 0
    for p in sorted(Path(args.folder).glob("*_notes.zip")):
        n = statement_tags.load(db, p)
        total += n
        print(json.dumps({"file": p.name, "rows": n}), flush=True)
    print(json.dumps({"rows": total}))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
