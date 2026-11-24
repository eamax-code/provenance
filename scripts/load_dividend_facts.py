#!/usr/bin/env python
"""Q-04: load dividends declared per share into dividend_facts from the SEC's bulk company facts
(SEC_BULK_DIR/companyfacts.zip), for the companies stored here, through the same normalizer and
upsert as financial_facts. The hourly ingest keeps it current after that.

  python scripts/load_dividend_facts.py --dry-run --out sample.jsonl   # count, store nothing
  python scripts/load_dividend_facts.py                                # store (upsert)
  python scripts/load_dividend_facts.py --since-bulk                   # catch up from the cache

--since-bulk: companies ingested after the bulk file was published (its Last-Modified), from
their cached company facts (no SEC requests), so the bulk load plus the ingest leave no gap.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Company, DividendFact, utcnow
from app.services.fact_normalizer import DIVIDEND_CONCEPTS, normalize_company_facts
from app.services.ingestion import upsert_facts

TAGS = (b"CommonStockDividendsPerShareDeclared", b"CommonStockDividendsPerShareCashPaid")


def catch_up(db, settings, path: Path, dry_run: bool) -> int:
    from email.utils import parsedate_to_datetime

    from app.services.sec_client import SecClient, company_facts_url

    meta = json.loads(Path(str(path) + ".meta.json").read_text())
    published = parsedate_to_datetime(meta["last_modified_raw"])
    sec = SecClient(settings)
    ciks = sorted(db.scalars(select(Company.cik).where(
        Company.last_successful_fetch_at >= published)))  # fmt: skip
    stats: Counter = Counter(companies_since=len(ciks))
    now = utcnow()
    for cik in ciks:
        cached = sec._cache_read(company_facts_url(cik, settings.sec_base_data_url))
        if not cached or not isinstance(cached.get("body"), dict):
            stats["not_cached"] += 1
            continue
        facts = normalize_company_facts(cached["body"], cik, concepts=DIVIDEND_CONCEPTS)
        stats["with_dividends"] += bool(facts)
        stats["facts"] += len(facts)
        if facts and not dry_run:
            ins, _ = upsert_facts(db, cik, facts, now, model=DividendFact)
            stats["inserted"] += ins
    if not dry_run:
        db.commit()
    print(json.dumps({**stats, "published": published.isoformat(), "write": not dry_run}))
    sec.close()
    db.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="with --dry-run: every fact (JSONL)")
    ap.add_argument("--since-bulk", action="store_true")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    ciks = set(db.scalars(select(Company.cik)))
    path = Path(settings.sec_bulk_dir, "companyfacts.zip")
    if args.since_bulk:
        return catch_up(db, settings, path, args.dry_run)
    stats: Counter = Counter()
    units: Counter = Counter()
    out = open(args.out, "w") if args.out else None
    now = utcnow()
    with zipfile.ZipFile(path) as zf:
        for i, name in enumerate(zf.namelist(), 1):
            cik = name.removeprefix("CIK").removesuffix(".json")
            if cik not in ciks:
                continue
            raw = zf.read(name)
            if not any(t in raw for t in TAGS):
                continue
            facts = normalize_company_facts(json.loads(raw), cik, concepts=DIVIDEND_CONCEPTS)
            if not facts:
                continue
            stats["companies"] += 1
            stats["facts"] += len(facts)
            for f in facts:
                units[(f.unit, f.source_tag, f.period_class, f.quality_status)] += 1
                if out:
                    row = {"cik": cik, "value": str(f.value), "unit": f.unit,
                           "start": str(f.period_start), "end": str(f.period_end),
                           "class": f.period_class, "fy": f.fiscal_year, "fp": f.fiscal_period,
                           "form": f.form_type, "filed": str(f.filed_date),
                           "acc": f.accession_number, "tag": f.source_tag,
                           "q": f.quality_status}  # fmt: skip
                    out.write(json.dumps(row) + "\n")
            if not args.dry_run:
                ins, _ = upsert_facts(db, cik, facts, now, model=DividendFact)
                stats["inserted"] += ins
                if stats["companies"] % 200 == 0:
                    db.commit()
            if i % 2000 == 0:
                print(json.dumps({"members": i, **stats}), flush=True)
    if not args.dry_run:
        db.commit()
    if out:
        out.close()
    top = {" | ".join(map(str, k)): v for k, v in units.most_common(25)}
    print(json.dumps({**stats, "write": not args.dry_run, "by_unit_tag_class_quality": top},
                     indent=1))  # fmt: skip
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
