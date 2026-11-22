#!/usr/bin/env python
"""Fail when a stored fact is on an older mapping and is not a reviewed exception.

  python scripts/check_mapping.py      # exit 1 and list what is unexpected

Run after a full pass. Old rows the SEC no longer publishes are listed after review in
app/data/mapping_exceptions.csv; anything else on an older mapping means its company was not in
the pass and needs a per-company refresh (scripts/ingest_company.py).
"""

from __future__ import annotations

import json
import sys

from _bootstrap import bootstrap

from app.services import mapping_check


def main() -> int:
    _, Session = bootstrap()
    out = mapping_check.check(Session())
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
