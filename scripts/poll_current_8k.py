#!/usr/bin/env python
"""Read 8-K item 5.02 officer changes from EDGAR's latest-filings feed within minutes.

Usage: python scripts/poll_current_8k.py --once     # one poll
       python scripts/poll_current_8k.py            # every CURRENT_8K_POLL_SECONDS (default 45)

Extraction uses the local language model when LLM_ENABLED is true; without it the 5.02 sections
are fetched and stored, and read once the model is available.
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap

from app.jobs.current_8k import run_forever, run_once
from app.services.sec_client import SecClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings, Session = bootstrap()
    if not args.once:
        run_forever(Session, settings)
        return 0
    from app.services.llm import LocalLLM

    db, sec = Session(), SecClient(settings)
    try:
        llm = LocalLLM(settings) if settings.llm_enabled else None
        print(json.dumps(run_once(db, settings, sec, llm)))
    finally:
        db.close()
        sec.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
