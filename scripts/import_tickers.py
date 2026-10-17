#!/usr/bin/env python
"""Load the SEC ticker/exchange mapping into the companies table (identity only, no filings)."""

from __future__ import annotations

import sys

from _bootstrap import bootstrap

from app.services.ingestion import import_ticker_mapping
from app.services.sec_client import SecClient, SecClientError


def main() -> int:
    settings, Session = bootstrap()
    db = Session()
    client = SecClient(settings)
    try:
        resp = client.fetch_ticker_exchange()
        stats = import_ticker_mapping(db, resp.data)
        db.commit()
        print(f"ticker mapping imported: {stats} (from_cache={resp.from_cache})")
        return 0
    except SecClientError as exc:
        print(f"SEC request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
