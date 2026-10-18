#!/usr/bin/env python
"""Create an API key from the command line (the protected admin path for the MVP).

Usage: python scripts/create_api_key.py dev@example.com --plan free --label "local dev"
The raw key is printed once and never stored.
"""

from __future__ import annotations

import argparse
import sys

from _bootstrap import bootstrap

from app.core.config import PLAN_NAMES
from app.services.api_keys import create_key_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner_email")
    parser.add_argument("--plan", default="free", choices=list(PLAN_NAMES))
    parser.add_argument("--label", default=None)
    args = parser.parse_args()
    settings, Session = bootstrap()
    problems = [p for p in settings.validate_for_runtime() if "PEPPER" in p]
    if problems:
        print("; ".join(problems), file=sys.stderr)
        return 2
    db = Session()
    try:
        key, raw = create_key_record(
            db, settings, args.owner_email, args.plan, args.label, actor="script"
        )
        db.commit()
        print(f"key_id={key.id} prefix={key.key_prefix} plan={key.plan}")
        print(f"API key (shown once): {raw}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
