"""Delete rate-limit counter rows keyed on a raw IP or email address.

Run once on any database that served requests before the keys were hashed (2026-11-23).
Counters expire after two days (rate_limits.KEEP_SECONDS), so this only speeds that up.

    .venv/bin/python scripts/purge_rate_limit_identifiers.py
"""

from __future__ import annotations

from _bootstrap import bootstrap

from app.core.rate_limits import purge_raw_identifiers
from app.db.session import get_engine


def main() -> None:
    bootstrap()
    print(f"purged {purge_raw_identifiers(get_engine())} counter keys holding an address")


if __name__ == "__main__":
    main()
