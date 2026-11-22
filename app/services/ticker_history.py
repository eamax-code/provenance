"""Ticker history from the trading symbols companies tag on their own filings (backlog K-04b).

Since 2019 every 10-K, 10-Q and 8-K cover tags each class of registered securities with
dei:TradingSymbol, dei:SecurityExchangeName and dei:Security12bTitle. The SEC's Financial
Statement and Notes data sets carry them (app.services.auditors reads them in the same pass), so
a symbol a company used before its current one can be dated from its own filings, back to 2019,
instead of only from the day a change is first seen (K-04).

A symbol the company no longer has becomes a former ticker (the alias search already reads),
valid from the first filing that tagged it to the last. Debt and other non-equity classes (notes,
debentures, preferred, warrants, units, rights) are left out, as are placeholders (N/A, NONE).
Only the registrant's undimensioned symbol is read: a company with several classes tags each
on a class-of-stock dimension, so its symbols are not used here (no false "former" ticker).
"""

from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyAlias

_NOT_EQUITY = re.compile(
    r"\bnotes?\b|debenture|%|preferred|depositary shares? each representing|warrant|\bunits?\b|"
    r"\brights?\b|bonds?|trust preferred|guarantee",
    re.I,
)
_PLACEHOLDER = {"", "N/A", "NA", "NONE", "-", "--", "NOT APPLICABLE"}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def norm(symbol: str | None) -> str:
    """BRK.B and BRK-B are the same symbol."""
    return (symbol or "").strip().upper().replace(".", "-")


def usable(row: dict) -> bool:
    s = norm(row.get("symbol"))
    return (
        s not in _PLACEHOLDER
        and bool(_SYMBOL.match(s))
        and not _NOT_EQUITY.search(row.get("title") or "")
        and row.get("filed_date") is not None
    )


def segments(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{cik: {symbol: {first, last}}} by filing date, equity symbols only."""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if not usable(r):
            continue
        s = norm(r["symbol"])
        seg = out.setdefault(r["cik"], {}).setdefault(s, {"first": r["filed_date"],
                                                          "last": r["filed_date"]})  # fmt: skip
        seg["first"] = min(seg["first"], r["filed_date"])
        seg["last"] = max(seg["last"], r["filed_date"])
    return out


def _current(company: Company) -> set[str]:
    now = {norm(company.ticker)} if company.ticker else set()
    try:
        now |= {norm(t) for t in json.loads(company.tickers or "[]") if t}
    except ValueError:
        pass
    return now


def apply(db: Session, rows: list[dict]) -> dict:
    """Store former tickers dated from the company's filings; widen the dates of ones already
    known. A symbol still current is never a former ticker."""
    segs = segments(rows)
    companies = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(list(segs))))}
    added = widened = 0
    for cik, by_symbol in segs.items():
        company = companies.get(cik)
        if company is None:
            continue
        current = _current(company)
        if not current:
            continue  # no current ticker to compare with: nothing is "former"
        for symbol, seg in by_symbol.items():
            if symbol in current:
                continue
            row = db.get(CompanyAlias, (cik, symbol))
            if row is None:
                db.add(CompanyAlias(cik=cik, alias=symbol, kind="former_ticker",
                                    valid_from=seg["first"], valid_to=seg["last"]))  # fmt: skip
                added += 1
            elif row.kind == "former_ticker":
                first = min(d for d in (row.valid_from, seg["first"]) if d)
                last = max(d for d in (row.valid_to, seg["last"]) if d)
                if (first, last) != (row.valid_from, row.valid_to):
                    row.valid_from, row.valid_to = first, last
                    widened += 1
    db.commit()
    return {"companies": len(segs), "former_tickers_added": added, "widened": widened}


def dated(rows: list[dict], cik: str) -> list[tuple[str, date, date]]:
    """A company's symbols with the first and last filing that tagged them, oldest first."""
    segs = segments(rows).get(cik, {})
    return sorted(((s, v["first"], v["last"]) for s, v in segs.items()), key=lambda x: x[1])
