"""Annual statements for one company, point in time (launch plan D-01, U-01).

One cell per metric and fiscal year: the figure reported in the annual report for that year (an
annual report over a proxy's repeat of it), the latest filed, and with `as_of` only what had
been filed by that date. Ratios are derived here from the cells and list their inputs.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialFact
from app.services import periods, ratios, successions
from app.services.fact_normalizer import CONCEPT_MAP, currency_from_unit, default_unit
from app.services.intel import ANNUAL_FORMS
from app.services.point_in_time import known_by

SECTIONS = (
    ("income", "Income statement"),
    ("balance", "Balance sheet"),
    ("cash_flow", "Cash flow"),
)


def _pref(f: FinancialFact, own: str = "") -> tuple:
    """The company's own filing over a predecessor's (K-05), an annual report over a proxy's
    repeat, then the latest filed."""
    return (f.cik == own, f.form_type in ANNUAL_FORMS, f.filed_date or date.min,
            f.accession_number or "")  # fmt: skip


def registrant(f: FinancialFact, own: str) -> dict:
    """K-05: which registrant filed the figure; a predecessor's rows say so."""
    if f.cik == own:
        return {"registrant_cik": f.cik, "predecessor": False}
    label = f"Reported by predecessor registrant (CIK {int(f.cik)})"
    return {"registrant_cik": f.cik, "predecessor": True, "registrant_label": label}


def _cell(f: FinancialFact, fiscal_label: str, own: str | None = None) -> dict:
    return {
        **registrant(f, own or f.cik),
        "fiscal_label": fiscal_label,
        "period_end": f.period_end.isoformat(),
        "value": float(f.value),
        "form_type": f.form_type,
        "filed_date": f.filed_date.isoformat() if f.filed_date else None,
        "accession_number": f.accession_number,
        "source_url": f.source_url,
        "quality_status": f.quality_status,
        "derived": False,
    }


def annual_cells(
    db: Session, company: Company, as_of: date | None = None, metrics: tuple[str, ...] | None = None
) -> tuple[dict[str, dict[str, FinancialFact]], dict[str, str], dict[str, date]]:
    """({metric: {fiscal_label: fact}}, {metric: unit}, {fiscal_label: period_end}). A successor
    registrant's figures continue with its predecessors' (K-05), each fact under its own CIK."""
    wanted = metrics or tuple(m for m, s in CONCEPT_MAP.items() if s["statement"] != "cover")
    ciks = [company.cik] + [p.predecessor_cik for p in successions.predecessors(db, company.cik)]
    stmt = select(FinancialFact).where(
        FinancialFact.cik.in_(ciks),
        FinancialFact.metric.in_(wanted),
        FinancialFact.period_class == "annual",
        FinancialFact.derived.is_(False),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.value.is_not(None),
    )
    if as_of:
        stmt = known_by(stmt, as_of)
    rows = db.scalars(stmt).all()
    # one unit per metric: the one with the most fiscal years (the reporting currency; IFRS
    # filers add a USD convenience translation for the latest year only), USD on a tie
    units: dict[str, str] = {}
    for m in wanted:
        years: dict[str, set] = {}
        for r in rows:
            if r.metric == m:
                years.setdefault(r.unit, set()).add(r.period_end)
        if years:
            own = default_unit(m)
            units[m] = max(years, key=lambda u: (len(years[u]), u == own))
    best: dict[str, dict[date, FinancialFact]] = {}
    for r in rows:
        if units.get(r.metric) != r.unit:
            continue
        cur = best.setdefault(r.metric, {}).get(r.period_end)
        if cur is None or _pref(r, company.cik) > _pref(cur, company.cik):
            best[r.metric][r.period_end] = r
    fye = company.fiscal_year_end
    by_label: dict[str, dict[str, FinancialFact]] = {}
    ends: dict[str, date] = {}
    for m, per_end in best.items():
        for end, f in per_end.items():
            lab = periods.label(end, "annual", fye)
            prev = by_label.setdefault(m, {}).get(lab)
            if prev is None or f.period_end > prev.period_end:
                by_label[m][lab] = f
            if lab not in ends or end > ends[lab]:
                ends[lab] = end
    return by_label, units, ends


def build(db: Session, company: Company, as_of: date | None = None, years: int = 5) -> dict:
    cells, units, ends = annual_cells(db, company, as_of)
    flows = [lab for m, per in cells.items() if CONCEPT_MAP[m]["statement"] != "balance"
             for lab in per]  # fmt: skip
    labels = sorted(set(flows) or set(ends), key=lambda lab: ends[lab])[-years:]
    sections = []
    for key, title in SECTIONS:
        rows = []
        for m, spec in CONCEPT_MAP.items():
            if spec["statement"] != key or m not in cells:
                continue
            row_cells = [_cell(cells[m][lab], lab, company.cik) if lab in cells[m] else None
                         for lab in labels]  # fmt: skip
            if not any(row_cells):
                continue
            rows.append({"metric": m, "label": spec["label"], "unit": units[m],
                         "currency": currency_from_unit(units[m]), "derived": False,
                         "cells": row_cells})  # fmt: skip
        if rows:
            sections.append({"key": key, "title": title, "rows": rows})
    ratio_rows = []
    for name, r in ratios.RATIOS.items():
        num, den = cells.get(r.numerator, {}), cells.get(r.denominator, {})
        if not num or not den or not ratios.compatible(r, units[r.numerator], units[r.denominator]):
            continue  # inputs missing here (cover facts), or two currencies
        row_cells = []
        for lab in labels:
            n, d = num.get(lab), den.get(lab)
            value = ratios.compute(r, float(n.value) if n else None, float(d.value) if d else None)
            row_cells.append(None if value is None else {
                "fiscal_label": lab, "period_end": ends[lab].isoformat(), "value": value,
                "derived": True, "accession_number": n.accession_number,
                **registrant(n, company.cik),
                "inputs": [{"metric": f.metric, "value": float(f.value),
                            "accession_number": f.accession_number, "source_url": f.source_url}
                           for f in (n, d)],
            })  # fmt: skip
        if any(row_cells):
            unit = ratios.unit_of(r, units[r.numerator])
            ratio_rows.append({
                "metric": name, "label": r.label, "unit": unit,
                "currency": currency_from_unit(unit) if r.kind == "difference" else None,
                "derived": True, "formula": r.formula, "inputs": [r.numerator, r.denominator],
                "cells": row_cells,
            })  # fmt: skip
    if ratio_rows:
        sections.append({"key": "ratios", "title": "Ratios", "rows": ratio_rows})
    return {"fiscal_years": labels, "sections": sections}
