#!/usr/bin/env python
"""Print the pilot's measures from docs/launch-plan.md (accounts, first call, activation,
weekly active keys, MCP share, data quality).

Usage: python scripts/pilot_metrics.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import bootstrap

from app.services import pilot_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()
    _settings, Session = bootstrap()
    db = Session()
    try:
        m = pilot_metrics.collect(db)
        print(json.dumps(m, indent=2) if args.json else pilot_metrics.render(m))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
