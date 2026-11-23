#!/usr/bin/env python
"""D-13: read SEC comment letters (UPLOAD) and company responses (CORRESP) since 2019 for the
read set, through the SEC client, and store their file number, subject, topics and whether the
review closed (docs/contracts/comment-letters.md).

  python scripts/read_comment_letters.py --showcase --largest 100 --dry-run --sample 40
  python scripts/read_comment_letters.py --showcase --largest 100

A dry run fetches and parses but stores nothing, and prints a sample for the hand-check.
"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from pathlib import Path

from _bootstrap import bootstrap
from read_10k_sections import largest

from app.db.models import CommentLetter
from app.services import comment_letters
from app.services.public import showcase_ciks
from app.services.sec_client import SecClient, SecClientError, normalize_cik


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ciks", default="")
    ap.add_argument("--showcase", action="store_true")
    ap.add_argument("--largest", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--out", default=None, help="with --dry-run: write every parsed row here")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    ciks = [normalize_cik(c) for c in args.ciks.split(",") if c.strip()]
    if args.showcase:
        ciks += [c for c in showcase_ciks(db, settings)[0] if c not in ciks]
    if args.largest:
        ciks += [c for c in largest(db, args.largest) if c not in ciks]
    todo = comment_letters.letters_to_read(db, ciks)
    print(json.dumps({"companies": len(ciks), "letters": len(todo)}), flush=True)
    rows, failed = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(todo):
            try:
                row = comment_letters.read(db, sec, f, Path(tmp))
            except SecClientError as exc:
                failed += 1
                print(json.dumps({"accession_number": f.accession_number, "error": str(exc)[:160]}))
                continue
            rows.append(row)
            if not args.dry_run:
                db.merge(CommentLetter(**row))
                if len(rows) % 100 == 0:
                    db.commit()
            if i % 100 == 0:
                print(json.dumps({"done": i, "of": len(todo)}), flush=True)
    if not args.dry_run:
        db.commit()
    stats = {"read": len(rows), "failed": failed,
             "readable": sum(r["readable"] for r in rows),
             "with_file_number": sum(bool(r["file_number"]) for r in rows),
             "closing": sum(r["closes_review"] for r in rows),
             "acceleration_requests": sum(r["kind"] == "acceleration_request" for r in rows)}
    print(json.dumps(stats), flush=True)
    if args.dry_run and args.out:
        Path(args.out).write_text(json.dumps(rows, default=str))
    if args.dry_run and args.sample:
        random.seed(13)
        for r in random.sample(rows, min(args.sample, len(rows))):
            print(json.dumps({k: (v[:400] if k == "text" and v else v) for k, v in r.items()},
                             default=str))
    sec.close()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
