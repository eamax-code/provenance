"""Facts left on an older concept mapping after a full pass (scripts/check_mapping.py).

Some observations cannot be re-read: the SEC's company facts no longer publish them, so no pass
reaches them. They stay as reported, on the mapping that read them, and each company is listed
after review in app/data/mapping_exceptions.csv (company, mapping, row count, reason, date
checked). The check passes only when every old row is a reviewed exception: a company not in the
file, another mapping version, or more rows than the file allows means a pass missed something.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import FinancialFact
from app.services.fact_normalizer import MAPPING_VERSION

EXCEPTIONS = Path(__file__).resolve().parents[1] / "data" / "mapping_exceptions.csv"


def reviewed(path: Path = EXCEPTIONS) -> dict[tuple[str, str], int]:
    """{(cik, mapping_version): allowed rows} from the reviewed exceptions file."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {(r["cik"], r["mapping_version"]): int(r["rows"]) for r in csv.DictReader(fh)}


def check(db: Session, path: Path = EXCEPTIONS) -> dict:
    rows = db.execute(
        select(FinancialFact.cik, FinancialFact.mapping_version, func.count())
        .where(FinancialFact.mapping_version != MAPPING_VERSION)
        .group_by(FinancialFact.cik, FinancialFact.mapping_version)
    ).all()
    allowed = reviewed(path)
    unexpected, expected = [], 0
    for cik, version, n in rows:
        cap = allowed.get((cik, version))
        if cap is not None and n <= cap:
            expected += n
        else:
            unexpected.append({"cik": cik, "mapping_version": version, "rows": n,
                               "reviewed_rows": cap})  # fmt: skip
    bad = sum(u["rows"] for u in unexpected)
    return {
        "current": MAPPING_VERSION,
        "ok": not unexpected,
        "summary": f"{bad} unexpected old rows ({expected} reviewed exceptions)",
        "unexpected": unexpected,
    }
