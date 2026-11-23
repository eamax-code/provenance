#!/usr/bin/env python
"""D-14: GLEIF Level 2 parents and exceptions, the names they refer to, and exhibit 21
subsidiaries linked to LEIs (docs/contracts/corporate-tree.md).

  python scripts/load_gleif_level2.py --dry-run --save /tmp/l2.json --sample 30
  python scripts/load_gleif_level2.py --from /tmp/l2.json        # write what the dry run read

Downloads the golden copy's relationship and exception files once (cached, like Level 1) and
reads the cached Level 1 file for names. GLEIF is CC0; no GLEIF URL is ever served.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from _bootstrap import bootstrap

from app.services import gleif_level2 as L2
from app.services import lei_golden
from app.services.identity import norm_key
from app.services.markets.http import MarketHttp


def fetch(settings, kind: str):
    http = MarketHttp(settings)
    data = http.get_json(lei_golden.GOLDEN_LATEST)
    data = data.get("data", data)
    url = data[kind]["full_file"]["csv"]["url"]
    big = MarketHttp(settings, http=http.http, cache_dir=http.cache_dir,
                     max_bytes=lei_golden.GOLDEN_MAX_BYTES, sleep=http._sleep)  # fmt: skip
    return big.download(url, cache_key="gleif-golden/" + url.rsplit("/", 1)[-1]).path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save", default=None)
    ap.add_argument("--from", dest="source", default=None)
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    if args.source:
        saved = json.loads(Path(args.source).read_text())
        rels, exc, names, links = saved["rels"], saved["exc"], saved["names"], saved["links"]
        for r in rels:
            r["period_start"] = r["period_start"] and __import__("datetime").date.fromisoformat(
                r["period_start"])
    else:
        rels, exc = L2.parse_level2(db, fetch(settings, "rr"), fetch(settings, "repex"))
        subs = L2.latest_subsidiaries(db)
        leis = {r["child_lei"] for r in rels} | {r["parent_lei"] for r in rels}
        names, by_key = L2.scan_level1(fetch(settings, "lei2"), leis,
                                       {norm_key(s.name) for s in subs})  # fmt: skip
        links = L2.match_subsidiaries(subs, by_key)
        names |= {lei: {"lei": lei, "legal_name": n, "jurisdiction": j, "entity_status": st}
                  for cands in by_key.values() for lei, j, n, st in cands
                  if lei in {x["lei"] for x in links}}  # fmt: skip
        print(json.dumps({"relationships": len(rels), "exceptions": len(exc), "names": len(names),
                          "latest_ex21_rows": len(subs), "subsidiary_links": len(links)}))
        if args.save:
            Path(args.save).write_text(json.dumps(
                {"rels": rels, "exc": exc, "names": names, "links": links}, default=str))
        if args.sample:
            by_id = {s.id: s for s in subs}
            random.seed(21)
            for x in random.sample(links, min(args.sample, len(links))):
                s = by_id[x["subsidiary_id"]]
                n = names[x["lei"]]
                print(json.dumps({"cik": s.cik, "ex21": s.name, "ex21_jur": s.jurisdiction,
                                  "lei": x["lei"], "gleif": n["legal_name"],
                                  "gleif_jur": n["jurisdiction"]}))  # fmt: skip
    if not args.dry_run:
        print(json.dumps(L2.store(db, rels, exc, names, links)))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
