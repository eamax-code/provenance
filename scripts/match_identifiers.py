#!/usr/bin/env python
"""Link SEC filers to their LEI and listings abroad (launch plan K-01).

  python scripts/match_identifiers.py

Uses the SEC's own LEI, then GLEIF names and jurisdictions; hand-checked links in lei_overrides
always win. The daily listings job runs it after GLEIF enrichment.
"""

from __future__ import annotations

import json

from _bootstrap import bootstrap

from app.services import identity


def main() -> int:
    _, Session = bootstrap()
    db = Session()
    print(json.dumps(identity.match_all(db)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
