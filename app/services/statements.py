"""Annual statements for one company, point in time (launch plan D-01, U-01).

One cell per metric and fiscal year: the figure reported in the annual report for that year (an
annual report over a proxy's repeat of it), the latest filed, and with `as_of` only what had
been filed by that date. Ratios are derived here from the cells and list their inputs.
"""

from __future__ import annotations

import csv
from datetime import date
from functools import lru_cache
from pathlib import Path

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
        "source_tag": f.source_tag,  # the provenance card needs no second call (X-01a)
        "mapping_version": f.mapping_version,
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


SHARE_ROWS = ("shares_basic_weighted", "shares_diluted_weighted", "shares_outstanding")
EPS_ROWS = ("eps_basic", "eps_diluted")
SPLIT_MIN_FACTOR = 1.9
SPLIT_INTEGER_TOLERANCE = 0.10  # the factor within 10% of a whole number (buybacks move it)
SPLIT_MAX_INCOME_SWING = 2.0  # shares x EPS (about net income) changes by less than 2x
# S-02b: a pair outside that swing (NVIDIA's FY2023, the 10:1 split year: net income fell 55%)
# counts only with a clean ratio found in the reviewed split list (confirm, from the route). A
# later filing's restatement alone was tried and failed the hand-check: 7 of 30 were corrections
# or had the ratio off by one (Starz 15:1 read as 14:1).
SPLIT_MAX_CLEAN_FACTOR = 100
REVIEWED_SPLITS = Path(__file__).resolve().parents[1] / "data" / "splits_reviewed.csv"


@lru_cache(maxsize=1)
def reviewed_splits() -> set[tuple[str, str]]:
    """(cik, ratio) of splits read in the filing's own disclosure (app/data/splits_reviewed.csv)."""
    with REVIEWED_SPLITS.open(newline="") as f:
        return {(r["cik"], r["ratio"]) for r in csv.DictReader(f)}


def split_breaks(values: dict[str, list[float | None]], keys: list[str],
                 confirm=None) -> dict[str, dict]:  # fmt: skip
    """Where adjacent columns mix share bases: a later filing restated some years for a stock
    split and the earlier years stay as originally filed (Apple FY2017 5.2B shares, FY2018
    19.8B). Flag only, nothing is adjusted: a share row jumps by a near-whole factor and an EPS
    row moves inversely across the same pair. Returns {metric: {"between": [a, b],
    "ratio_hint": "4:1"}} for each share and EPS row with values on both sides of the latest
    such pair; "1:4" is a reverse split. confirm(between, hint) may accept a pair whose income
    swing is too large (S-02b): the route checks the reviewed split list."""
    found = None
    for i in range(1, len(keys)):
        for s in SHARE_ROWS:
            a, b = (values.get(s) or [None] * len(keys))[i - 1 : i + 1]
            if not a or not b or a <= 0 or b <= 0:
                continue
            r = b / a
            factor = max(r, 1 / r)
            whole = round(factor)
            if factor < SPLIT_MIN_FACTOR or abs(factor / whole - 1) > SPLIT_INTEGER_TOLERANCE:
                continue
            for e in EPS_ROWS:
                x, y = (values.get(e) or [None] * len(keys))[i - 1 : i + 1]
                if not x or not y or (x > 0) != (y > 0):
                    continue
                inverse = (y / x < 1) == (r > 1)
                swing = r * (y / x)
                hint = f"{whole}:1" if r > 1 else f"1:{whole}"
                if inverse and (1 / SPLIT_MAX_INCOME_SWING < swing < SPLIT_MAX_INCOME_SWING
                                or (confirm is not None and whole <= SPLIT_MAX_CLEAN_FACTOR
                                    and confirm([keys[i - 1], keys[i]], hint))):  # fmt: skip
                    found = (i, hint)
                    break
            if found and found[0] == i:
                break
    if not found:
        return {}
    i, hint = found
    out = {}
    for m in SHARE_ROWS + EPS_ROWS:
        a, b = (values.get(m) or [None] * len(keys))[i - 1 : i + 1]
        if a and b:
            out[m] = {"between": [keys[i - 1], keys[i]], "ratio_hint": hint}
    return out


def split_adjusted(db, cik: str, rows: list, breaks: dict, as_of=None) -> dict[str, dict]:
    """S-02: a split-adjusted series beside the as-filed one, for the share and EPS rows of a
    statement with a split break. The ratio comes from the filings: a period before the break
    that a later filing reports again, restated by a near-whole factor (Apple FY2018 diluted EPS
    11.91 as filed, 2.98 in the 10-K filed 2020-10-30). Each value before the break is the
    restated one when a later filing gives it, else the as-filed value adjusted by that ratio;
    later values are unchanged. Derived, never the default. {} when no filing confirms a ratio
    (the flag alone stays)."""
    from app.db.models import FinancialFact

    if not breaks:
        return {}
    wanted = SHARE_ROWS + EPS_ROWS
    by_metric = {r.metric: r for r in rows if not r.derived and r.metric in wanted}
    brk = next(iter(breaks.values()))
    old_key = brk["between"][0]
    a, b = brk["ratio_hint"].split(":")
    expected = float(int(a)) if int(b) == 1 else 1 / int(b)  # the break's own split
    any_row = next(iter(by_metric.values()), None)
    if any_row is None:
        return {}
    cols = [c.column if c else None for c in any_row.cells]
    for r in by_metric.values():  # the column labels, from any row that has them
        cols = [a or (c.column if c else None) for a, c in zip(cols, r.cells, strict=False)]
    if old_key not in cols:
        return {}
    cut = cols.index(old_key)  # columns 0..cut are on the old share basis

    def reported(metric, cell) -> list:
        q = select(FinancialFact).where(
            FinancialFact.cik == cik, FinancialFact.metric == metric,
            FinancialFact.period_end == cell.period_end,
            FinancialFact.period_start == cell.period_start,
            FinancialFact.derived.is_(False), FinancialFact.value.is_not(None))  # fmt: skip
        if as_of:
            q = q.where(FinancialFact.filed_date <= as_of)
        return list(db.scalars(q.order_by(FinancialFact.filed_date)))

    def share_factor(metric, orig, later) -> float | None:
        """New shares per old share, when the restatement is a near-whole split."""
        r = float(later.value) / float(orig.value)
        if metric in EPS_ROWS:
            r = 1 / r
        if r <= 0:
            return None
        whole = round(r) if r >= 1 else 1 / round(1 / r)
        big = r if r >= 1 else 1 / r
        if big < SPLIT_MIN_FACTOR or abs(big / round(big) - 1) > SPLIT_INTEGER_TOLERANCE:
            return None
        return float(whole)

    factor = evidence = None
    for metric in EPS_ROWS + SHARE_ROWS:
        row = by_metric.get(metric)
        # the first new-basis year (Apple FY2018: 11.91 as filed, 2.98 restated) and then the
        # old-basis years, newest first; an older split (Apple 7:1, 2014) is not this one
        for cell in reversed(row.cells[: cut + 2]) if row else []:
            if cell is None:
                continue
            facts = reported(metric, cell)
            for later in facts[1:]:
                if later.filed_date > facts[0].filed_date and facts[0].value and later.value:
                    f = share_factor(metric, facts[0], later)
                    if f and abs(f / expected - 1) < 1e-9:  # the restatement is this split
                        factor, evidence = f, (metric, cell, facts[0], later)
                        break
            if factor:
                break
        if factor:
            break
    if not factor:
        return {}
    metric, cell, orig, later = evidence
    source = {
        "accession_number": later.accession_number, "form": later.form_type,
        "filed_date": later.filed_date.isoformat(), "source_url": later.source_url,
        "evidence": f"{metric} for the period ending {cell.period_end.isoformat()}: "
        f"{float(orig.value):g} as filed {orig.filed_date.isoformat()}, "
        f"{float(later.value):g} in the {later.form_type} filed {later.filed_date.isoformat()}",
    }  # fmt: skip
    ratio = f"{round(factor)}:1" if factor >= 1 else f"1:{round(1 / factor)}"
    out = {}
    for m, row in by_metric.items():
        values = []
        for i, c in enumerate(row.cells):
            if c is None or i > cut:
                values.append(c.value if c else None)
                continue
            v = float(c.value)
            new = v * factor if m in SHARE_ROWS else v / factor
            # a later filing's own restated value wins when it agrees with the ratio
            again = [float(f.value) for f in reported(m, c)[1:] if f.value]
            match = next((x for x in reversed(again) if new and abs(x / new - 1) < 0.02), None)
            values.append(round(match if match is not None else new, 6))
        out[m] = {"ratio": ratio, "derived": True, "values": values, "source": source,
                  "basis": "Before the split: a later filing's restated value where it gives "
                  "one, else the as-filed value adjusted by the ratio the filings "
                  "show."}  # fmt: skip
    return out
