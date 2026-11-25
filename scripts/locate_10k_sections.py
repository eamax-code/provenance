#!/usr/bin/env python
"""Q-09: set filed_text and layout (heading, offsets, subheadings, document) on the stored 10-K
items (10k:1A, 10k:7) from the SEC client's cache of their documents (no SEC requests; a
document not cached is counted and left as it is).

  python scripts/locate_10k_sections.py --dry-run     # count, store nothing
  python scripts/locate_10k_sections.py               # store
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Filing, FilingSection
from app.services import tenk_sections
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    rows = list(db.scalars(select(FilingSection).where(
        FilingSection.item.in_(list(tenk_sections.ITEMS.values())),
        FilingSection.status == "ok")))  # fmt: skip
    docs = dict(db.execute(select(Filing.accession_number, Filing.primary_document).where(
        Filing.accession_number.in_({r.accession_number for r in rows}))).all())  # fmt: skip
    stats: Counter = Counter(sections=len(rows))
    for r in rows:
        cached = sec._cache_read(r.source_url)  # the cache only: never a request
        if not cached or not cached.get("body"):
            stats["not_cached"] += 1
            continue
        filed, layout = tenk_sections.layout_of(cached["body"], r.item.split(":")[1],
                                                docs.get(r.accession_number))  # fmt: skip
        if filed is None:
            stats["not_located"] += 1
            continue
        stats["located"] += 1
        stats["with_subheadings"] += bool(json.loads(layout)["subheadings"])
        if not args.dry_run:
            r.filed_text, r.layout = filed, layout
    if not args.dry_run:
        db.commit()
    sec.close()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
