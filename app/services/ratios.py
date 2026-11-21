"""Derived figures (ADR 0003 style, launch plan D-03): computed at query time from two reported
figures, never stored, always marked derived with their inputs listed.

Inputs are paired by period (same period class and period end), or for a per-share figure by
filing (the cover page's shares outstanding sit in the same annual report as the balance
sheet). Two figures in different currencies are never combined.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.fact_normalizer import METRIC_UNIT_KIND, currency_from_unit


@dataclass(frozen=True)
class Ratio:
    label: str
    numerator: str
    denominator: str
    formula: str
    kind: str = "percent"  # percent (x100) | multiple | difference | per_share


RATIOS: dict[str, Ratio] = {
    "gross_margin": Ratio("Gross margin", "gross_profit", "revenue", "Gross profit / Revenue"),
    "operating_margin": Ratio(
        "Operating margin", "operating_income", "revenue", "Operating income / Revenue"
    ),
    "net_margin": Ratio("Net margin", "net_income", "revenue", "Net income / Revenue"),
    "return_on_assets": Ratio(
        "Return on assets", "net_income", "total_assets", "Net income / Total assets (period end)"
    ),
    "return_on_equity": Ratio(
        "Return on equity", "net_income", "stockholders_equity",
        "Net income / Stockholders' equity (period end)",
    ),
    "free_cash_flow": Ratio(
        "Free cash flow", "operating_cash_flow", "capex",
        "Operating cash flow - Capital expenditure", kind="difference",
    ),
    "debt_to_equity": Ratio(
        "Long-term debt to equity", "long_term_debt", "stockholders_equity",
        "Long-term debt / Stockholders' equity", kind="multiple",
    ),
    "current_ratio": Ratio(
        "Current ratio", "current_assets", "current_liabilities",
        "Current assets / Current liabilities", kind="multiple",
    ),
    "book_value_per_share": Ratio(
        "Book value per share", "stockholders_equity", "shares_outstanding",
        "Stockholders' equity / Shares outstanding (cover page of the same report)",
        kind="per_share",
    ),
}  # fmt: skip
DERIVED_METRICS = tuple(RATIOS)


def unit_of(ratio: Ratio, numerator_unit: str) -> str:
    if ratio.kind == "percent":
        return "%"
    if ratio.kind == "multiple":
        return "x"
    if ratio.kind == "per_share":
        return f"{currency_from_unit(numerator_unit) or numerator_unit}/shares"
    return numerator_unit


def compute(ratio: Ratio, numerator: float | None, denominator: float | None) -> float | None:
    """The derived value, or None when an input is missing or a divisor is not positive."""
    if numerator is None or denominator is None:
        return None
    if ratio.kind == "difference":
        return numerator - denominator
    if denominator <= 0:
        return None
    value = numerator / denominator
    return round(value * 100, 1) if ratio.kind == "percent" else round(value, 2)


def compatible(ratio: Ratio, num_unit: str, den_unit: str) -> bool:
    if METRIC_UNIT_KIND.get(ratio.denominator) == "shares":
        return den_unit == "shares" and currency_from_unit(num_unit) is not None
    return num_unit == den_unit  # never divide or subtract across currencies


def pair_key(ratio: Ratio, f) -> tuple:
    if ratio.kind == "per_share":
        return ("filing", f.accession_number)
    return ("period", f.period_class, f.period_end)


def derive(ratio: Ratio, numerators: list, denominators: list) -> list[dict]:
    """Pairs of fact-like objects (metric, value, unit, period_class, period_end, ...) turned
    into derived values, one per matched period."""
    by_key: dict[tuple, object] = {}
    for d in denominators:
        if d.value is not None:
            by_key.setdefault(pair_key(ratio, d), d)
    out = []
    for n in numerators:
        d = by_key.get(pair_key(ratio, n))
        if d is None or n.value is None or not compatible(ratio, n.unit, d.unit):
            continue
        value = compute(ratio, float(n.value), float(d.value))
        if value is None:
            continue
        out.append({"value": Decimal(str(value)), "unit": unit_of(ratio, n.unit),
                    "numerator": n, "denominator": d})  # fmt: skip
    return out


def ref(f) -> dict:
    return {
        "metric": f.metric,
        "value": str(f.value),
        "unit": f.unit,
        "period_end": f.period_end.isoformat(),
        "accession_number": f.accession_number,
        "source_url": f.source_url,
    }
