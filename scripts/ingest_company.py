#!/usr/bin/env python
"""Ingest one company from the SEC by CIK or ticker.

Usage: python scripts/ingest_company.py 320193
       python scripts/ingest_company.py AAPL
"""

from __future__ import annotations

import argparse
import sys

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import Company
from app.services.ingestion import ingest_company
from app.services.sec_client import SecClient, SecClientError, is_cik_like, normalize_cik


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identifier", help="CIK (any zero padding) or ticker symbol")
    parser.add_argument("--no-facts", action="store_true", help="Skip company-facts ingestion")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    try:
        if is_cik_like(args.identifier):
            cik = normalize_cik(args.identifier)
        else:
            company = db.scalar(
                select(Company).where(func.upper(Company.ticker) == args.identifier.upper())
            )
            if company is None:
                print(
                    "Ticker not found locally. Run scripts/import_tickers.py first or pass a CIK.",
                    file=sys.stderr,
                )
                return 2
            cik = company.cik
        client = SecClient(settings)
        try:
            result = ingest_company(db, client, cik, include_facts=not args.no_facts)
        finally:
            client.close()
        print(
            f"cik={result.cik} filings_seen={result.filings_seen} "
            f"filings_inserted={result.filings_inserted} "
            f"facts_seen={result.facts_seen} facts_inserted={result.facts_inserted} "
            f"facts_available={result.facts_available} errors={result.errors}"
        )
        return 0
    except SecClientError as exc:
        print(f"SEC request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
