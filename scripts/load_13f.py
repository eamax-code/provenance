#!/usr/bin/env python
"""Institutional ownership from Form 13F (launch plan E-1).

  python scripts/load_13f.py --fetch-only            # Schedules 13D/G into the SEC cache only
  python scripts/load_13f.py --datasets .sec_bulk/13f  # map CUSIPs, then load the 13F zips

1. The CUSIP map: for each company with a structured Schedule 13D or 13G, the latest one is
   read (cached on disk by the SEC client, so --fetch-only first and loading later costs no
   second request) and its CUSIPs are mapped to the issuer; then US and CA ISINs of listings
   linked by LEI.
2. The Form 13F data sets in the folder, oldest first (download them from
   sec.gov/data-research/sec-markets-data/form-13f-data-sets), stored per filing; other share
   classes of mapped issuers are added from the titles the 13Fs give.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import Filing
from app.services import cusips, thirteenf
from app.services.beneficial_owners import XML_FORMS, _doc_url
from app.services.sec_client import SecClient, SecClientError


def latest_schedules(db, limit: int | None) -> list[Filing]:
    last = (
        select(Filing.cik, func.max(Filing.filing_date).label("d"))
        .where(Filing.form_type.in_(XML_FORMS))
        .group_by(Filing.cik)
        .subquery()
    )
    rows = db.scalars(
        select(Filing)
        .join(last, (Filing.cik == last.c.cik) & (Filing.filing_date == last.c.d))
        .where(Filing.form_type.in_(XML_FORMS))
        .order_by(Filing.cik, Filing.accession_number.desc())
    ).all()
    one = {}
    for f in rows:
        one.setdefault(f.cik, f)
    out = list(one.values())
    return out[:limit] if limit else out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch-only", action="store_true", help="Fill the SEC cache, no writes")
    ap.add_argument("--datasets", help="Folder with *_form13f.zip data sets")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    # plain values: reading ORM rows after the transaction ends would reload them and leave a
    # transaction open for the whole fetch
    todo = [
        (_doc_url(f), f.accession_number, f.filing_date) for f in latest_schedules(db, args.limit)
    ]
    db.rollback()
    mapped = failed = 0
    for i, (url, accession, filed) in enumerate(todo, 1):
        if url is None:
            continue
        try:
            text = sec.get_text(url).data
        except SecClientError:
            failed += 1
            continue
        if not args.fetch_only:
            try:
                mapped += cusips.record_schedule(db, text, accession, filed)
            except (ValueError, ElementTree.ParseError):
                failed += 1
        if i % 500 == 0:
            db.commit()  # also ends the transaction in --fetch-only
            print(json.dumps({"schedules": i, "of": len(todo), "mapped": mapped}), flush=True)
    out = {"schedules": len(todo), "cusips_mapped": mapped, "failed": failed}
    if not args.fetch_only:
        out["isin_mapped"] = cusips.map_isins(db)
        db.commit()
        if args.datasets:
            zips = sorted(Path(args.datasets).glob("*_form13f.zip"),
                          key=lambda p: thirteenf.window_end(p) or p.stem)  # fmt: skip
            out["datasets"] = [{"file": p.name, **thirteenf.load_dataset(db, p)} for p in zips]
    print(json.dumps(out, default=str))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
