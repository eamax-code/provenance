#!/usr/bin/env python
"""Purge api_usage and finished notification deliveries beyond the configured retention windows.

Usage: python scripts/retention.py            (USAGE_RETENTION_DAYS / DELIVERY_RETENTION_DAYS)
"""

from __future__ import annotations

import json
import sys

from _bootstrap import bootstrap

from app.services import retention


def main() -> int:
    settings, Session = bootstrap()
    db = Session()
    try:
        print(json.dumps(retention.purge(db, settings)))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
