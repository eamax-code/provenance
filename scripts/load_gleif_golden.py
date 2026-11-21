#!/usr/bin/env python
"""Load LEIs for every SEC filer from the GLEIF golden copy (CC0; launch plan K-01b).

  python scripts/load_gleif_golden.py

Downloads the latest full file once (about 490 MB zipped, cached), keeps only entities whose
exact legal name matches an SEC filer, then relinks filers to LEIs under the strict rules.
"""

from __future__ import annotations

import json

from _bootstrap import bootstrap

from app.services import identity, lei_golden
from app.services.markets.http import MarketHttp


def main() -> int:
    settings, Session = bootstrap()
    db = Session()
    http = MarketHttp(settings)
    meta = http.get_json(lei_golden.GOLDEN_LATEST)
    data = meta.get("data", meta)
    url = data["lei2"]["full_file"]["csv"]["url"]
    big = MarketHttp(settings, http=http.http, cache_dir=http.cache_dir,
                     max_bytes=lei_golden.GOLDEN_MAX_BYTES, sleep=http._sleep)  # fmt: skip
    fetched = big.download(url, cache_key="gleif-golden/" + url.rsplit("/", 1)[-1])
    loaded = lei_golden.load(db, fetched.path)
    print(json.dumps({"golden": loaded, "links": identity.match_all(db)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
