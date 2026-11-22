#!/usr/bin/env python
"""Segment labels from each filing's label linkbase (launch plan E-4b).

  python scripts/load_segment_labels.py            # every annual report with segments
  python scripts/load_segment_labels.py --latest   # each company's latest report only

One filing index and one label linkbase per report, through the shared SEC limiter (filed
documents are cached, so a rerun sends no requests for reports already read). Members a company
did not label itself keep the label made from the member name.
"""

from __future__ import annotations

import argparse
import json

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import CompanySegment
from app.services import segment_labels
from app.services.sec_client import SecClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Only each company's latest report (the one the overview shows)",
    )
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    stmt = select(CompanySegment.cik, CompanySegment.accession_number).distinct()
    if args.latest:
        stmt = (
            select(CompanySegment.cik, CompanySegment.accession_number)
            .distinct(CompanySegment.cik)
            .order_by(CompanySegment.cik, CompanySegment.filed_date.desc(),
                      CompanySegment.accession_number.desc())
        )  # fmt: skip
    todo = db.execute(stmt).all()
    db.rollback()
    out = {"reports": len(todo), "rows_relabelled": 0, "reports_relabelled": 0}
    for i, (cik, acc) in enumerate(todo, 1):
        n = segment_labels.apply_filing(db, sec, cik, acc)
        out["rows_relabelled"] += n
        out["reports_relabelled"] += n > 0
        if i % 250 == 0:
            print(json.dumps({**out, "done": i}), flush=True)
    print(json.dumps(out))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
