#!/usr/bin/env python
"""S-05: set each company's fiscal-year naming convention from its latest 10-K's own wording.

python scripts/set_fiscal_year_offsets.py --dry-run --fetch --out d.jsonl  # read, store nothing
python scripts/set_fiscal_year_offsets.py --out d.jsonl                    # store (cache only)

Candidates are the companies whose filings' DEI fiscal year most often differs from the end-year
rule. For each, the primary document of its latest annual filing is read (from the SEC cache;
with --fetch, missing ones are fetched through SecClient, which paces and caches them). Where it
names the year it reports in words, that offset is stored (for every year: the report names its
prior years the same way); everyone else is null (the end-year rule). Stops on a 403 or 429.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import select, update

from app.db.models import Company, Filing
from app.services import fiscal_convention as fc
from app.services.sec_client import SecClient, SecClientError


def latest_annual(db, cik: str) -> Filing | None:
    """The company's latest original annual report (not an amendment)."""
    return db.scalar(select(Filing)
                     .where(Filing.cik == cik, Filing.form_type.in_(fc.ANNUAL_FORMS),
                            Filing.form_type.not_like("%/A"),  # an amendment is often Part III only
                            Filing.primary_document.is_not(None))
                     .order_by(Filing.filing_date.desc()).limit(1))  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fetch", action="store_true", help="fetch documents missing from the cache")
    ap.add_argument("--out", default=None, help="one line per candidate (JSONL)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if args.fetch and not args.dry_run:
        ap.error("--fetch only with --dry-run: fetch first, then write from the cache")
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    by_cik = fc.filings(db)
    cands = fc.candidates(by_cik)[: args.limit]
    stats: Counter = Counter(candidates=len(cands))
    decided: dict[str, int | None] = {}
    out = open(args.out, "w") if args.out else None
    for cik in cands:
        company = db.scalar(select(Company).where(Company.cik == cik))
        filing = latest_annual(db, cik)
        row = {"cik": cik, "name": company.legal_name, "ticker": company.ticker,
               "fye": company.fiscal_year_end,
               "dei": dict(Counter(d for _, d, _ in by_cik[cik]))}  # fmt: skip
        doc = None
        if filing is None:
            stats["no annual document"] += 1
        else:
            url = fc.document_url(cik, filing.accession_number, filing.primary_document)
            row.update(accession=filing.accession_number, form=filing.form_type, url=url)
            if sec._cache_read(url):
                stats["cached"] += 1
            elif not args.fetch:
                stats["not cached"] += 1
                url = None
            else:
                stats["fetched"] += 1
            try:
                doc = sec.get_text(url).data if url else None
            except SecClientError as exc:
                if exc.status_code in (403, 429):
                    print(f"SEC {exc.status_code}: stopping", file=sys.stderr)
                    stats["stopped"] = exc.status_code
                    break
                stats["failed"] += 1
                row["error"] = str(exc)[:120]
        # the year end the filing reports: only statements naming it count
        own = filing and (filing.report_date or next(
            (e for e, _, a in by_cik[cik] if a == filing.accession_number), None))  # fmt: skip
        counts = fc.wording(doc, company.fiscal_year_end, own) if doc and own else Counter()
        off = fc.wording_offset(counts)
        disagree = fc.dei_disagrees(by_cik[cik], off, company.fiscal_year_end) if off else []
        stats[f"wording offset {off}"] += 1
        if disagree:
            stats["DEI names some years otherwise (listed, not applied)"] += 1
        decided[cik] = off
        row.update(own_year_end=own.isoformat() if own else None, wording=dict(counts),
                   offset=off, dei_disagrees_years=disagree)  # fmt: skip
        if out:
            out.write(json.dumps(row) + "\n")
    sec.close()
    if out:
        out.close()
    if not args.dry_run and "stopped" not in stats:
        db.execute(update(Company).where(Company.fiscal_year_offset.is_not(None))
                   .values(fiscal_year_offset=None))  # fmt: skip
        for cik, off in decided.items():
            if off is not None:
                db.execute(update(Company).where(Company.cik == cik).values(fiscal_year_offset=off))
        db.commit()
    print(json.dumps({**stats, "write": not args.dry_run and "stopped" not in stats}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
