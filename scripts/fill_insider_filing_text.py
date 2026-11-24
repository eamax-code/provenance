#!/usr/bin/env python
"""F-03e: signatures, remarks and footnotes for Forms 3/4/5 read as filed (after the data sets)
that have an entity reporting owner, from the document cache only (no SEC requests; a filing
not cached is counted and skipped).

  python scripts/fill_insider_filing_text.py --dry-run --out rows.jsonl
  python scripts/fill_insider_filing_text.py
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Filing, InsiderFiling, InsiderFilingText
from app.services import insiders
from app.services.sec_client import SecClient


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    have = select(InsiderFilingText.accession_number)
    rows = db.execute(select(InsiderFiling.accession_number, InsiderFiling.owner_name)
                      .where(InsiderFiling.source == "filing",
                             InsiderFiling.accession_number.not_in(have))).all()  # fmt: skip
    todo = sorted({a for a, n in rows if insiders.is_entity(n)})
    stats = {"entity_filings": len(todo), "not_cached": 0, "no_xml": 0, "parsed": 0}
    out = open(args.out, "w") if args.out else None
    for acc in todo:
        f = db.scalar(select(Filing).where(Filing.accession_number == acc))
        url = insiders._xml_url(f) if f is not None else None
        if url is None:
            stats["no_xml"] += 1
            continue
        cached = sec._cache_read(url)  # the cache only: never a request
        if not cached or not cached.get("body"):
            stats["not_cached"] += 1
            continue
        parsed = insiders.parse_ownership_xml(cached["body"], acc, f.filing_date)
        if acc not in parsed.texts:
            stats["no_xml"] += 1
            continue
        stats["parsed"] += 1
        if out:
            out.write(json.dumps({"accession_number": acc, "issuer_cik": f.cik,
                                  **parsed.texts[acc]}) + "\n")  # fmt: skip
        if not args.dry_run:
            insiders.store_texts(db, parsed, "filing")
    if out:
        out.close()
    if not args.dry_run:
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run}))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
