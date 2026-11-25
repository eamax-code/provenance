#!/usr/bin/env python
"""D-01b: read the successor each stopped registrant's own filings name.

The reader is app/services/named_successors.py.

Reads, through SecClient (cached, 8 requests a second or fewer, stopping on 403 or 429), the
primary document of each stopped registrant's 8-Ks with Item 2.01 or 5.01 near its last periodic
report, and of every successor 8-K12B/8-K12G3 held. Display only: figures are never joined.

  python scripts/find_named_successors.py --dry-run --out found.jsonl   # read, store nothing
  python scripts/find_named_successors.py                               # store
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

from _bootstrap import bootstrap
from sqlalchemy import select

from app.db.models import Company, CompanyAlias
from app.services import named_successors as N
from app.services.sec_client import SecClient, SecClientError, SecNotFound
from app.services.tenk_sections import paragraphs


def doc_url(f) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(f.cik)}/"
            f"{f.accession_number.replace('-', '')}/{f.primary_document}")  # fmt: skip


def read_paras(sec, f) -> list[str] | None:
    if not f.primary_document:
        return None
    try:
        body = sec.get_text(doc_url(f)).data
    except SecNotFound:
        return None
    except SecClientError as e:
        if e.status_code in (403, 429):
            raise  # fair access: stop the run
        return None  # a transient error (502): this filing is counted unreadable
    if f.primary_document.lower().endswith(".txt"):
        return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return [p for p, _ in paragraphs(body)]


def own_names(db, cik: str) -> set[str]:
    names = {N.norm(db.scalar(select(Company.legal_name).where(Company.cik == cik)))}
    names |= {N.norm(a) for a in db.scalars(select(CompanyAlias.alias).where(
        CompanyAlias.cik == cik, CompanyAlias.kind == "former"))}  # fmt: skip
    return {n for n in names if n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="write every link found (JSON lines) here")
    ap.add_argument("--limit", type=int, help="read at most this many filings of each kind")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    names = N.Names(db)
    pred, succ, stopped = N.candidates(db)
    pred, succ = pred[: args.limit], succ[: args.limit]
    stats: Counter = Counter(predecessor_8k=len(pred), successor_8k12=len(succ))
    rows = []
    try:
        for f in pred:
            paras = read_paras(sec, f)
            if not paras:
                stats["unreadable"] += 1
                continue
            got = N.read_predecessor(paras, f.cik, own_names(db, f.cik), names, f.filing_date)
            if got:
                rows.append({**got, "predecessor_cik": f.cik,
                             "evidence_accession": f.accession_number,
                             "evidence_form": f.form_type, "evidence_date": f.filing_date,
                             "evidence_url": doc_url(f)})  # fmt: skip
        for f in succ:
            paras = read_paras(sec, f)
            if not paras:
                stats["unreadable"] += 1
                continue
            got = N.read_successor(paras, f.cik, own_names(db, f.cik), names, f.filing_date)
            if got and got["predecessor_cik"] in stopped:
                rows.append({**got, "evidence_accession": f.accession_number,
                             "evidence_form": f.form_type, "evidence_date": f.filing_date,
                             "evidence_url": doc_url(f)})  # fmt: skip
    except SecClientError as e:
        print(f"stopped: {e}", file=sys.stderr)  # 403/429: stop, rerun later (cached)
        stats["stopped"] += 1
    chosen = N.choose(rows)
    stats["links_found"] = len(rows)
    stats["predecessors_linked"] = len(chosen)
    stats.update(Counter(f"kind_{r['kind']}" for r in chosen.values()))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for r in chosen.values():
                fh.write(json.dumps(r, default=str) + "\n")
    if not args.dry_run and not stats["stopped"]:
        stats.update(N.store(db, chosen))
        db.commit()
    sec.close()
    print(json.dumps({**stats, "write": not args.dry_run}, indent=1))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
