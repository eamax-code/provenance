#!/usr/bin/env python
"""Federal Reserve H.10 daily exchange rates, full history (public domain), for USD-equivalent
size cohorts.
  python scripts/load_fx.py
One request to federalreserve.gov (cached), never through the SEC limiter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from _bootstrap import bootstrap

from app.db.models import JobState
from app.services import fx
from app.services.markets.http import MarketHttp


def main() -> int:
    settings, Session = bootstrap()
    db = Session()
    http = MarketHttp(settings)
    today = datetime.now(UTC).date()
    url = fx.h10_url(today)
    fetched = http.download(url, cache_key=f"fed-h10/h10-{today.isoformat()}.csv")
    text = fetched.path.read_text(encoding="utf-8", errors="replace")
    if not fx.parse_h10(text):
        # an empty or HTML answer is not kept, so the next run fetches again
        fetched.path.unlink(missing_ok=True)
        print(json.dumps({"error": "the H.10 file had no rates; nothing replaced"}))
        return 1
    n = fx.load(db, text)
    # where the rates came from, for operators only (never in a response)
    state = db.get(JobState, "fx:h10") or JobState(name="fx:h10", value="")
    state.value = json.dumps({"source": fx.SOURCE_NAME, "url": url, "rows": n,
                              "loaded_at": datetime.now(UTC).isoformat()})  # fmt: skip
    db.merge(state)
    db.commit()
    print(json.dumps({"rows": n}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
