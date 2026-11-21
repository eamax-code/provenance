"""Derived ratios (ADR 0003 style): computed at query time from two reported figures of the same
fiscal year, never stored, always marked derived with their inputs (launch plan D-03)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ratio:
    label: str
    numerator: str
    denominator: str
    formula: str
    unit: str = "%"  # % (x100) or "x" (a plain multiple)


RATIOS: dict[str, Ratio] = {
    "gross_margin": Ratio("Gross margin", "gross_profit", "revenue", "Gross profit / Revenue"),
    "operating_margin": Ratio(
        "Operating margin", "operating_income", "revenue", "Operating income / Revenue"
    ),
    "net_margin": Ratio("Net margin", "net_income", "revenue", "Net income / Revenue"),
    "return_on_assets": Ratio(
        "Return on assets", "net_income", "total_assets", "Net income / Total assets (year end)"
    ),
}


def compute(ratio: Ratio, numerator: float | None, denominator: float | None) -> float | None:
    """The ratio, or None when an input is missing or the denominator is not positive."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    value = numerator / denominator
    return round(value * 100, 1) if ratio.unit == "%" else round(value, 2)
