#!/usr/bin/env python
"""F-03d: store the signatures, remarks and footnotes of Forms 3/4/5 with an entity reporting
owner, from the SEC insider data sets in SEC_BULK_DIR/insiders (no SEC requests).

  python scripts/load_insider_filing_text.py --dry-run --out sample.jsonl   # count, store nothing
  python scripts/load_insider_filing_text.py                                # store (replaces)
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import delete, insert

from app.db.models import InsiderFilingText
from app.services import insiders
from app.services.insider_screener import unquote


def read(path: Path) -> list[dict]:
    """The rows for one data set: filings with at least one entity reporting owner."""
    quarter = path.name.split("_")[0]
    with zipfile.ZipFile(path) as zf:
        entity = {r["ACCESSION_NUMBER"] for r in insiders._tsv(zf, "REPORTINGOWNER.TSV")
                  if insiders.is_entity(r.get("RPTOWNERNAME") or "")}  # fmt: skip
        sig: dict[str, list[str]] = {}
        for r in insiders._tsv(zf, "OWNER_SIGNATURE.TSV"):
            if r["ACCESSION_NUMBER"] in entity and r.get("OWNERSIGNATURENAME"):
                sig.setdefault(r["ACCESSION_NUMBER"], []).append(unquote(r["OWNERSIGNATURENAME"]))
        notes: dict[str, list[str]] = {}
        for r in insiders._tsv(zf, "FOOTNOTES.TSV"):
            if r["ACCESSION_NUMBER"] in entity and r.get("FOOTNOTE_TXT"):
                notes.setdefault(r["ACCESSION_NUMBER"], []).append(unquote(r["FOOTNOTE_TXT"]))
        # the data sets keep CSV quoting on some texts ('"a ""b"" c"'): unquoted as filed
        remarks = {r["ACCESSION_NUMBER"]: unquote(r.get("REMARKS")) or None
                   for r in insiders._tsv(zf, "SUBMISSION.TSV")
                   if r["ACCESSION_NUMBER"] in entity}  # fmt: skip
    return [{"accession_number": a, "signatures": json.dumps(sig.get(a, [])),
             "remarks": remarks.get(a), "footnotes": json.dumps(notes.get(a, [])),
             "source": f"dataset:{quarter}"} for a in sorted(entity)]  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None, help="with --dry-run: write the rows here (JSONL)")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    rows: dict[str, dict] = {}
    for path in sorted(Path(settings.sec_bulk_dir, "insiders").glob("*_form345.zip")):
        got = read(path)
        for r in got:
            rows[r["accession_number"]] = r  # a later data set wins
        print(json.dumps({"dataset": path.name, "entity_filings": len(got)}), flush=True)
    stats = {"filings": len(rows),
             "with_signature": sum(r["signatures"] != "[]" for r in rows.values()),
             "with_remarks": sum(bool(r["remarks"]) for r in rows.values()),
             "with_footnotes": sum(r["footnotes"] != "[]" for r in rows.values())}  # fmt: skip
    if args.dry_run:
        if args.out:
            with open(args.out, "w") as f:
                for r in rows.values():
                    f.write(json.dumps(r) + "\n")
        print(json.dumps(stats))
        return 0
    db.execute(delete(InsiderFilingText))
    batch = list(rows.values())
    for i in range(0, len(batch), 20_000):
        db.execute(insert(InsiderFilingText), batch[i : i + 20_000])
    db.commit()
    print(json.dumps({**stats, "stored": len(batch)}))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
