#!/usr/bin/env python
"""D-15: Form D private raises from the SEC's structured Form D data sets (last 8 quarters).

  python scripts/load_form_d.py --quarters 8      # download through the SEC client, then load
  python scripts/load_form_d.py --folder .sec_bulk/formd

Downloads into SEC_BULK_DIR/formd (fetched internally; every offering links to its filing on
sec.gov/Archives). Loading a quarter again replaces its filings; is_latest is recomputed.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _bootstrap import bootstrap

from app.services import form_d
from app.services.sec_client import SecClient

PAGE = "https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quarters", type=int, default=0)
    ap.add_argument("--folder", default=None)
    args = ap.parse_args()
    settings, Session = bootstrap()
    folder = Path(args.folder or Path(settings.sec_bulk_dir) / "formd")
    folder.mkdir(parents=True, exist_ok=True)
    if args.quarters:
        sec = SecClient(settings)
        page = sec.get_text(PAGE).data
        found = {}
        for href, q in re.findall(r'href="([^"]*/(\d{4}q[1-4])_d\.zip)"', page, re.I):
            found[q.lower()] = href if href.startswith("http") else "https://www.sec.gov" + href
        for q in sorted(found)[-args.quarters :]:
            sec.download_file(found[q], folder / f"{q}_d.zip")
        sec.close()
    db = Session()
    print(json.dumps(form_d.load(db, sorted(folder.glob("*_d.zip")))))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
