#!/usr/bin/env python
"""Institutional ownership from Form 13F (launch plan E-1).

  python scripts/load_13f.py --fetch-only            # Schedules 13D/G into the SEC cache only
  python scripts/load_13f.py --datasets .sec_bulk/13f  # map CUSIPs, then load the 13F zips
  python scripts/load_13f.py --name-rule .sec_bulk/13f/<latest>_form13f.zip   # E-1c (b)
  python scripts/load_13f.py --remove-reviewed .sec_bulk/13f [--apply]
      # delete the issuer_prefix links listed in app/data/cusip_removals_reviewed.csv

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
import zipfile
from collections import Counter
from datetime import date, timedelta
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


def deep_schedules(db, sec, per_company: int) -> dict:
    """E-1c (a): large companies whose latest schedule was one they filed as a holder (JPM,
    Berkshire file 13D/G on other issuers): read more of their schedules, newest first."""
    from sqlalchemy import exists

    from app.db.models import IssuerCusip, MartCompany

    since = date.today() - timedelta(days=730)
    todo = list(db.scalars(select(MartCompany.cik).where(
        MartCompany.reporting_currency == "USD", MartCompany.latest_revenue >= 1e9,
        MartCompany.latest_annual_report_date >= since,
        ~exists().where(IssuerCusip.cik == MartCompany.cik),
    )))  # fmt: skip
    mapped = read = 0
    for cik in todo:
        rows = [(_doc_url(f), f.accession_number, f.filing_date) for f in db.scalars(
            select(Filing).where(Filing.cik == cik, Filing.form_type.in_(XML_FORMS))
            .order_by(Filing.filing_date.desc()).limit(per_company))]  # fmt: skip
        db.rollback()
        for url, acc, filed in rows:
            if url is None:
                continue
            try:
                text = sec.get_text(url).data
                read += 1
                parsed = cusips.from_schedule(text)
            except (SecClientError, ValueError, ElementTree.ParseError):
                continue
            if parsed["issuer_cik"] == cik and parsed["cusips"]:
                cusips.record_schedule(db, text, acc, filed)
                db.commit()
                mapped += 1
                break
    return {"unmapped": len(todo), "schedules_read": read, "companies_mapped": mapped}


def remove_reviewed(db, folder: Path, apply: bool) -> dict:
    """Dry run unless `apply`: which reviewed links would go, and any reviewed row not found."""
    from sqlalchemy import select

    from app.db.models import IssuerCusip

    q = select(IssuerCusip.cusip).where(IssuerCusip.method == "issuer_prefix")
    prefixed = set(db.scalars(q))
    names: dict[str, set[str]] = {}
    for p in sorted(folder.glob("*_form13f.zip")):
        with zipfile.ZipFile(p) as z:
            for r in thirteenf._rows(z, "INFOTABLE.TSV"):
                c = (r.get("CUSIP") or "").strip().upper()
                if c in prefixed:
                    names.setdefault(c, set()).add(" ".join((r.get("NAMEOFISSUER") or "").split()))
    reviewed = cusips.reviewed_removals()
    gone = Counter(cusips.remove_reviewed(db, names, reviewed))
    # a row found with other than its checked number of links stops the write; a row with none
    # left was removed by an earlier run
    off = {"|".join(k): [n, gone[k]] for k, n in reviewed.items() if 0 < gone[k] != n}
    if apply and not off:
        db.commit()
    else:
        db.rollback()
    return {"applied": apply and not off, "reviewed_rows": len(reviewed),
            "removed": sum(gone.values()), "count_mismatch": off,
            "rows_already_removed": sum(1 for k in reviewed if not gone[k])}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch-only", action="store_true", help="Fill the SEC cache, no writes")
    ap.add_argument("--datasets", help="Folder with *_form13f.zip data sets")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--deep",
        type=int,
        default=0,
        metavar="N",
        help="E-1c (a): for active USD $1B+ companies still unmapped, read up to N of "
        "their recent schedules until one names the company as the issuer",
    )
    ap.add_argument("--name-rule", help="E-1c: map unmapped companies by 13F issuer name from "
                    "this data set (no schedules are read)")  # fmt: skip
    ap.add_argument(
        "--remove-reviewed",
        metavar="DIR",
        help="delete the issuer_prefix links on "
        "the reviewed list, matched by the 13F issuer names in DIR's data sets",
    )
    ap.add_argument("--apply", action="store_true", help="with --remove-reviewed: write")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    if args.remove_reviewed:
        print(json.dumps(remove_reviewed(db, Path(args.remove_reviewed), args.apply)))
        db.close()
        return 0
    if args.deep:
        print(json.dumps(deep_schedules(db, SecClient(settings), args.deep)))
        db.close()
        return 0
    if args.name_rule:
        stored = cusips.map_by_13f_names(db, thirteenf.issuer_names(args.name_rule))
        db.commit()
        print(json.dumps({"name_rule_mapped": len(stored),
                          "companies": len({c for c, _, _ in stored})}))  # fmt: skip
        db.close()
        return 0
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
