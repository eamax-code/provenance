#!/usr/bin/env python
"""S-08: load profit_loss (net income including noncontrolling interests, ProfitLoss) into
financial_facts from the SEC's bulk company facts (SEC_BULK_DIR/companyfacts.zip), for the
companies stored here, through the same normalizer and upsert as the ingest (mapping 1.6.0). The
hourly ingest keeps it current after that; nothing else is changed (upsert by observation key).

  python scripts/load_profit_loss.py --dry-run --out sample.jsonl   # count, store nothing
  python scripts/load_profit_loss.py                                # store (upsert)
  python scripts/load_profit_loss.py --since-bulk                   # catch up from the cache
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

from app.db.models import Company, utcnow
from app.services.fact_normalizer import CONCEPT_MAP, normalize_company_facts
from app.services.ingestion import upsert_facts

CONCEPTS = {"profit_loss": CONCEPT_MAP["profit_loss"]}


def _row(cik: str, f) -> dict:
    return {"cik": cik, "value": str(f.value), "unit": f.unit, "start": str(f.period_start),
            "end": str(f.period_end), "class": f.period_class, "form": f.form_type,
            "filed": str(f.filed_date), "acc": f.accession_number, "tag": f.source_tag,
            "tax": f.source_taxonomy, "q": f.quality_status}  # fmt: skip


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
        facts = normalize_company_facts(cached["body"], cik, concepts=CONCEPTS)
        stats["with_profit_loss"] += bool(facts)
        stats["facts"] += len(facts)
        if facts and not dry_run:
            stats["inserted"] += upsert_facts(db, cik, facts, now)[0]
    if not dry_run:
        db.commit()
    print(json.dumps({**stats, "published": published.isoformat(), "write": not dry_run}))
    sec.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="every fact (JSONL)")
    ap.add_argument("--since-bulk", action="store_true")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    path = Path(settings.sec_bulk_dir, "companyfacts.zip")
    if args.since_bulk:
        rc = catch_up(db, settings, path, args.dry_run)
        db.close()
        return rc
    ciks = set(db.scalars(select(Company.cik)))
    stats: Counter = Counter()
    kinds: Counter = Counter()
    out = open(args.out, "w") if args.out else None
    now = utcnow()
    with zipfile.ZipFile(path) as zf:
        for i, name in enumerate(zf.namelist(), 1):
            cik = name.removeprefix("CIK").removesuffix(".json")
            if cik not in ciks:
                continue
            raw = zf.read(name)
            if b'"ProfitLoss"' not in raw:
                continue
            facts = normalize_company_facts(json.loads(raw), cik, concepts=CONCEPTS)
            if not facts:
                continue
            stats["companies"] += 1
            stats["facts"] += len(facts)
            for f in facts:
                kinds[(f.source_taxonomy, f.period_class, f.quality_status)] += 1
                if out:
                    out.write(json.dumps(_row(cik, f)) + "\n")
            if not args.dry_run:
                stats["inserted"] += upsert_facts(db, cik, facts, now)[0]
                if stats["companies"] % 200 == 0:
                    db.commit()
            if i % 2000 == 0:
                print(json.dumps({"members": i, **stats}), flush=True)
    if not args.dry_run:
        db.commit()
    if out:
        out.close()
    top = {" | ".join(map(str, k)): v for k, v in kinds.most_common(20)}
    print(json.dumps({**stats, "write": not args.dry_run, "by_taxonomy_class_quality": top},
                     indent=1))  # fmt: skip
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
