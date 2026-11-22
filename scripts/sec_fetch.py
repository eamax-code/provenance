#!/usr/bin/env python
"""The one way to download a file from SEC by hand: through the SEC client, so every request
uses the contact User-Agent and the machine-wide rate limit (8 req/s across all jobs, a shared
pause on 403/429). Never curl or wget sec.gov directly (a test enforces it).

  python scripts/sec_fetch.py https://www.sec.gov/files/dera/.../2026_10_notes.zip .sec_bulk/fsn/
  python scripts/sec_fetch.py URL [URL ...] DEST_DIR

Existing files are revalidated with If-Modified-Since rather than downloaded again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import bootstrap

from app.services.sec_client import SecClient, SecClientError


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("urls", nargs="+", help="One or more sec.gov URLs, then the destination")
    ap.add_argument("--max-bytes", type=int, default=4_000_000_000)
    args = ap.parse_args()
    *urls, dest = args.urls
    if not urls:
        ap.error("give at least one URL and a destination directory")
    settings, _ = bootstrap(check_schema=False)  # no database needed
    sec = SecClient(settings)
    out_dir = Path(dest)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for url in urls:
        try:
            r = sec.download_file(url, out_dir / url.rsplit("/", 1)[-1], max_bytes=args.max_bytes)
            print(json.dumps({"url": url, "bytes": r["bytes"], "from_cache": r["from_cache"]}))
        except SecClientError as exc:
            failed += 1
            print(json.dumps({"url": url, "error": str(exc)}), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
