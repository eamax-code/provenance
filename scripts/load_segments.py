#!/usr/bin/env python
"""Segments from annual reports (launch plan E-4).

  python scripts/load_segments.py .sec_bulk/fsn     # every *_notes.zip in the folder

Loading a month again replaces its reports. Prints, per data set, the reports read and how many
kind/metric groups are unreconciled (the segments do not add up and no reconciling item).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.services import segments


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    for p in sorted(Path(args.folder).glob("*_notes.zip")):
        print(json.dumps({"file": p.name, **segments.load(db, p)}), flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
