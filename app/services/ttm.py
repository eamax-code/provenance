"""Trailing twelve months (X-01a, docs/api-contracts-explorer.md).

Flows (income statement, cash flow): the sum of the last four consecutive quarters, each the
quarter value /facts?period=quarterly gives (the latest filed observation; a Q4 derived as FY
minus nine months when not reported, marked). Balances: the latest period-end value. Only when
all four quarters exist, are consecutive, share one unit and the latest ends within 15 months of
the reference date. Every value is marked derived and lists its inputs. EPS is never summed.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialFact
from app.services.point_in_time import known_by

FLOWS = frozenset({
    "revenue", "cost_of_revenue", "gross_profit", "r_and_d", "sga", "operating_income",
    "interest_expense", "net_interest_income", "pretax_income", "income_tax", "net_income",
    "operating_cash_flow", "capex", "d_and_a", "sbc", "dividends_paid", "share_repurchases",
})  # fmt: skip
BALANCES = frozenset({
    "cash_and_equivalents", "current_assets", "total_assets", "current_liabilities",
    "long_term_debt_current", "long_term_debt", "total_liabilities", "stockholders_equity",
    "retained_earnings", "shares_outstanding",
})  # fmt: skip
RECENT_DAYS = 456  # about 15 months
OK = ("ok", "partial")


def _input(f) -> dict:
    return {"period_start": f.period_start.isoformat() if f.period_start else None,
            "period_end": f.period_end.isoformat(), "accession_number": f.accession_number,
            "source_url": f.source_url, "derived": bool(f.derived)}  # fmt: skip


def _quarters(db: Session, cik: str, metrics: list[str], as_of: date | None) -> dict:
    """{metric: {(period_end, unit): fact}}: reported quarters, plus derived Q4s."""
    from app.api.routes_companies import _row_to_normalized
    from app.services.fact_normalizer import NormalizedFact, derive_quarters

    q = select(FinancialFact).where(
        FinancialFact.cik == cik, FinancialFact.metric.in_(metrics),
        FinancialFact.derived.is_(False), FinancialFact.quality_status.in_(OK),
        FinancialFact.value.is_not(None),
    )  # fmt: skip
    if as_of:
        q = known_by(q, as_of)
    rows = list(db.scalars(q))
    out: dict[str, dict] = {}
    for f in rows:
        if f.period_class != "quarterly":
            continue
        key = (f.period_end, f.unit)
        cur = out.setdefault(f.metric, {}).get(key)
        if cur is None or (f.filed_date or date.min, f.accession_number or "") > (
            cur.filed_date or date.min,
            cur.accession_number or "",
        ):
            out[f.metric][key] = f
    durations = [_row_to_normalized(r) for r in rows if r.period_type == "duration"]
    for d in derive_quarters([n for n in durations if isinstance(n, NormalizedFact)]):
        out.setdefault(d.metric, {}).setdefault((d.period_end, d.unit), d)
    return out


def compute(db: Session, company: Company, metrics: list[str], as_of: date | None = None,
            today: date | None = None) -> dict[str, dict]:  # fmt: skip
    """{metric: {value, unit, period_end, derived, formula, inputs}} where it can be given."""
    ref = as_of or today or date.today()
    out: dict[str, dict] = {}
    flows = [m for m in metrics if m in FLOWS]
    if flows:
        quarters = _quarters(db, company.cik, flows, as_of)
        for m in flows:
            per = quarters.get(m, {})
            if not per:
                continue
            latest_end, unit = max(per)
            if (ref - latest_end).days > RECENT_DAYS or latest_end > ref:
                continue
            chain, end = [], latest_end
            for _ in range(4):
                f = per.get((end, unit))
                if f is None:
                    break
                chain.append(f)
                nxt = [e for (e, u) in per if u == unit and 80 <= (end - e).days <= 100]
                end = max(nxt) if nxt else None
                if end is None:
                    break
            if len(chain) == 4:
                out[m] = {"value": float(sum(f.value for f in chain)), "unit": unit,
                          "period_end": latest_end.isoformat(), "derived": True,
                          "formula": "sum of the last 4 quarters",
                          "inputs": [_input(f) for f in reversed(chain)]}  # fmt: skip
    for m in (m for m in metrics if m in BALANCES):
        q = select(FinancialFact).where(
            FinancialFact.cik == company.cik, FinancialFact.metric == m,
            FinancialFact.derived.is_(False), FinancialFact.quality_status.in_(OK),
            FinancialFact.value.is_not(None), FinancialFact.period_end <= ref,
            FinancialFact.period_end >= ref - timedelta(days=RECENT_DAYS),
        )  # fmt: skip
        if as_of:
            q = known_by(q, as_of)
        rows = list(db.scalars(q))
        if rows:
            f = max(rows, key=lambda r: (r.period_end, r.filed_date or date.min))
            out[m] = {"value": float(f.value), "unit": f.unit,
                      "period_end": f.period_end.isoformat(), "derived": True,
                      "formula": "latest balance", "inputs": [_input(f)]}  # fmt: skip
    return out
