#!/usr/bin/env python
"""Q-07: Item 4 (Purpose of Transaction) of structured Schedules 13D and 13D/A, as filed.

  python scripts/load_13d_purposes.py --dry-run     # fetch into the document cache, count
  python scripts/load_13d_purposes.py               # store (from the cache)

Through SecClient only (the shared 8/s limit, sec.gov/Archives documents); stops on a 403 or
429 rather than pushing through. Only the structured XML (December 2024 on) is read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Filing
from app.services.beneficial_owners import (
    _doc_url,
    item4,
    parse_schedule_xml,
    schedule_details,
    store_13d,
)
from app.services.sec_client import SecClient, SecClientError

FORMS = ("SCHEDULE 13D", "SCHEDULE 13D/A")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="the parsed texts (JSONL)")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    filings = db.execute(select(Filing.cik, Filing.accession_number, Filing.form_type,
                                Filing.filing_date, Filing.primary_document, Filing.source_url)
                         .where(Filing.form_type.in_(FORMS))
                         .order_by(Filing.filing_date)).all()  # fmt: skip
    db.rollback()
    c: Counter = Counter(filings=len(filings))
    out = open(args.out, "w") if args.out else None
    seen: set[str] = set()  # one filing is indexed under its subject and under its filer
    for i, f in enumerate(filings, 1):
        if f.accession_number in seen:
            c["duplicate_index_rows"] += 1
            continue
        seen.add(f.accession_number)
        url = _doc_url(f)
        if url is None or not url.startswith("https://www.sec.gov/Archives/"):
            c["no_xml"] += 1
            continue
        cached = sec._cache_read(url)
        if cached and isinstance(cached.get("body"), str):
            c["already_cached"] += 1
            body = cached["body"]
        else:
            try:
                body = sec.get_text(url).data
                c["fetched"] += 1
            except SecClientError as exc:
                c["failed"] += 1
                if re.search(r"\b(403|429)\b", str(exc)):
                    c["stopped_on"] = str(exc)[:120]
                    print(json.dumps({"stopped": i, **c}), flush=True)
                    break
                continue
        try:
            text = item4(body)
        except (ValueError, Exception):  # noqa: BLE001 - counted
            c["unparsed"] += 1
            continue
        c["item4_present" if text else "item4_empty"] += 1
        details = schedule_details(body)
        c["with_class_title"] += details["class_title"] is not None
        c["with_amendment_number"] += details["amendment_number"] is not None
        if text and re.search(r"\b(no (material )?change|unchanged|not amended|remains? "
                              r"unchanged)\b", text[:300], re.I):  # fmt: skip
            c["item4_says_unchanged"] += 1
        if not args.dry_run:
            subject = parse_schedule_xml(body)["issuer_cik"] or f.cik  # the issuer, from the XML
            store_13d(db, f.accession_number, subject, url, body)
            c["stored"] += 1
            if c["stored"] % 1000 == 0:
                db.commit()
        if out:
            out.write(json.dumps({"accession_number": f.accession_number, "cik": f.cik,
                                  "form": f.form_type, "filed": str(f.filing_date),
                                  "url": url, "item4": text, **details}) + "\n")  # fmt: skip
        if i % 500 == 0:
            print(json.dumps({"progress": i, **c}), flush=True)
    if out:
        out.close()
    if not args.dry_run:
        db.commit()
    print(json.dumps({**c, "write": not args.dry_run}))
    sec.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
