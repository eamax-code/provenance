"""Minimal Python client sample (requires `httpx`).

    API_KEY=prv_... python examples/client.py 320193
"""

from __future__ import annotations

import os
import sys
import time

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ["API_KEY"]


def main(cik: str) -> None:
    with httpx.Client(base_url=BASE_URL, headers={"X-API-Key": API_KEY}, timeout=30) as api:
        # Profile: 202 means on-demand ingestion is running; poll until 200 or 404.
        for _ in range(30):
            r = api.get(f"/v1/companies/{cik}")
            if r.status_code != 202:
                break
            time.sleep(int(r.headers.get("Retry-After", "5")))
        r.raise_for_status()
        profile = r.json()
        print(f"{profile['legal_name']} ({profile['ticker']}) CIK {profile['cik']}")
        print(f"  filings: {profile['filings_count']}  facts: {profile['facts_count']}")

        filings = api.get(f"/v1/companies/{cik}/filings", params={"limit": 3}).json()["data"]
        for f in filings:
            print(f"  {f['filing_date']} {f['form_type']:<6} accepted={f['accepted_at']} {f['source_url']}")

        facts = api.get(
            f"/v1/companies/{cik}/facts", params={"metric": "revenue", "period": "annual", "limit": 3}
        ).json()
        print(f"  mapping version {facts['mapping_version']}")
        for fact in facts["data"]:
            print(
                f"  revenue FY{fact['fiscal_year']} {fact['period_start']}..{fact['period_end']} "
                f"= {fact['value']} {fact['unit']} [{fact['source_tag']}] "
                f"{fact['quality_status']} <- {fact['accession_number']}"
            )

        fresh = api.get(f"/v1/companies/{cik}/freshness").json()
        print(f"  freshness: {fresh['status']} last fetch {fresh['last_successful_fetch_at']}")


def verify_webhook(secret: str, headers: dict, body: bytes) -> bool:
    """Copy this into your webhook receiver."""
    import hashlib
    import hmac
    import time as _time

    ts = headers["X-Signature-Timestamp"]
    if abs(_time.time() - int(ts)) > 300:
        return False
    expected = "v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Signature"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "320193")
