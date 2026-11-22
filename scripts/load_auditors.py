#!/usr/bin/env python
"""Audit firms from annual-report cover tags (launch plan E-3).

  python scripts/load_auditors.py .sec_bulk/fsn     # every *_notes.zip in the folder

Download the monthly Financial Statement and Notes data sets from
sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets first. Loading a
month again replaces its reports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.services import auditors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    for p in sorted(Path(args.folder).glob("*_notes.zip")):
        print(json.dumps({"file": p.name, **auditors.load(db, p)}), flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
