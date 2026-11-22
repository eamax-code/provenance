#!/usr/bin/env python
"""Former tickers dated from companies' own filings (backlog K-04b).

  python scripts/load_ticker_history.py .sec_bulk/fsn

Reads dei:TradingSymbol from every Financial Statement and Notes data set in the folder (each
month back to 2019 adds history) and stores the symbols a company no longer uses as former
tickers with the first and last filing dates that tagged them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.services import auditors, ticker_history


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    args = ap.parse_args()
    _, Session = bootstrap()
    db = Session()
    rows: list[dict] = []
    for p in sorted(Path(args.folder).glob("*_notes.zip")):
        rows += auditors.parse_notes_zip(p)[1]
    out = {"symbol_rows": len(rows), **ticker_history.apply(db, rows)}
    out["registrant_names_set"] = ticker_history.apply_registrant_names(db, rows)
    print(json.dumps(out))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
