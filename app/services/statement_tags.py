"""Revenue tags each filing places on its income statement, with its own labels (mapping 1.5.0).

Read from the Notes data sets' presentation table (pre.tsv): statement IS, not parenthetical,
standard US GAAP and IFRS revenue tags only. Mapping 1.5.0 uses it in two places:

- the tie-breaker: when a filing's revenue tags disagree, the one the filing shows on its income
  statement wins, but only when it is the only revenue candidate there (under any label) and its
  label reads as a total ("Revenues", "Total revenues", "Net sales"...); banks show component
  lines there ("Service charges on deposit accounts"), which never qualify;
- IFRS bank revenue: ifrs-full RevenueAndOperatingIncome, or GrossProfit at a bank, counts as
  revenue only where the income statement shows it under a total-income label ("Total operating
  income", "Total revenues", "Total income"). Bank revenue is that total income line, after
  interest expense, as the bank labels it.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import FilingStatementTag

US_GAAP = {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense",
           "RegulatedAndUnregulatedOperatingRevenue", "RegulatedOperatingRevenue"}  # fmt: skip
IFRS = {"Revenue", "RevenueFromContractsWithCustomers", "RevenueFromSaleOfGoods",
        "RevenueAndOperatingIncome", "GrossProfit"}  # fmt: skip
TAGS = US_GAAP | IFRS
TOTAL_LABEL = re.compile(
    r"^(total\s+)?(net\s+)?(operating\s+)?(revenues?|sales)(,?\s*net)?:?$"
    r"|^total revenues and other income$",
    re.I,
)
TOTAL_INCOME = re.compile(
    r"^(total\s+)?(net\s+)?operating\s+(income|profit)(\s*,?\s+before\b.*)?$"
    r"|^total\s+(net\s+)?revenues?$|^total\s+income$|^gross\s+income$",
    re.I,
)


def is_total(label: str | None) -> bool:
    return bool(label and TOTAL_LABEL.match(" ".join(label.split())))


def is_total_income(label: str | None) -> bool:
    return bool(label and TOTAL_INCOME.match(" ".join(label.split())))


def parse_zip(path: str | Path) -> list[dict]:
    """Income-statement revenue lines of every filing in one Notes data set."""
    source = "sec:fsn:" + Path(path).stem
    with zipfile.ZipFile(path) as z:

        def rows(name):
            fh = z.open(next(n for n in z.namelist() if n.lower().endswith(name)))
            return csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace",
                                                   newline=""),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)  # fmt: skip

        ciks = {r["adsh"]: r["cik"].zfill(10) for r in rows("sub.tsv")}
        out: dict[tuple, dict] = {}
        for r in rows("pre.tsv"):
            if r.get("stmt") != "IS" or r.get("inpth") != "0" or r.get("tag") not in TAGS:
                continue
            ver = r.get("version") or ""
            if not (ver.startswith("us-gaap") or ver.startswith("ifrs")):
                continue  # a company's own extension, never a standard tag
            adsh = r["adsh"]
            if adsh not in ciks:
                continue
            k = (adsh, r["tag"])
            if k not in out:  # the first line it appears on
                out[k] = {"accession_number": adsh, "tag": r["tag"], "cik": ciks[adsh],
                          "label": " ".join((r.get("plabel") or "").split())[:300],
                          "line": int(r["line"]) if (r.get("line") or "").isdigit() else None,
                          "source": source}  # fmt: skip
    return list(out.values())


def load(db: Session, path: str | Path) -> int:
    rows = parse_zip(path)
    accs = sorted({r["accession_number"] for r in rows})
    for i in range(0, len(accs), 1000):
        db.execute(delete(FilingStatementTag).where(
            FilingStatementTag.accession_number.in_(accs[i : i + 1000])))  # fmt: skip
    for i in range(0, len(rows), 5000):
        db.execute(insert(FilingStatementTag), rows[i : i + 5000])
    db.commit()
    return len(rows)


def for_company(db: Session, cik: str) -> dict[str, dict[str, str]]:
    """{accession: {tag: label}} for one company's filings."""
    out: dict[str, dict[str, str]] = {}
    for r in db.scalars(select(FilingStatementTag).where(FilingStatementTag.cik == cik)):
        out.setdefault(r.accession_number, {})[r.tag] = r.label
    return out
