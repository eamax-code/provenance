#!/usr/bin/env python
"""Fail when any stored fact is on a mapping version other than the current one.

  python scripts/check_mapping.py      # exit 1 and list the companies when some are

Run after a full pass: a fact left on an older mapping means its company was not in the pass
(for example a registrant not yet in the companyfacts archive) and needs a per-company refresh.
"""

from __future__ import annotations

import json
import sys

from _bootstrap import bootstrap
from sqlalchemy import func, select

from app.db.models import FinancialFact
from app.services.fact_normalizer import MAPPING_VERSION


def main() -> int:
    _, Session = bootstrap()
    db = Session()
    rows = db.execute(
        select(FinancialFact.cik, FinancialFact.mapping_version, func.count())
        .where(FinancialFact.mapping_version != MAPPING_VERSION)
        .group_by(FinancialFact.cik, FinancialFact.mapping_version)
    ).all()
    companies = [{"cik": c, "mapping_version": v, "rows": n} for c, v, n in rows]
    out = {"current": MAPPING_VERSION, "old_rows": sum(n for _, _, n in rows),
           "companies": companies}  # fmt: skip
    print(json.dumps(out))
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
