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
def reviewed_splits() -> dict[tuple[str, str], tuple[str, ...]]:
    """{(cik, ratio): effective dates} of splits read in the filing's own disclosure
    (app/data/splits_reviewed.csv); a company can split twice at one ratio (Amphenol 2:1 in 2021
    and 2024). A date is YYYY-MM-DD, YYYY-MM or empty, as precise as the filing states it."""
    out: dict[tuple[str, str], tuple[str, ...]] = {}
    with REVIEWED_SPLITS.open(newline="") as f:
        for r in csv.DictReader(f):
            out[(r["cik"], r["ratio"])] = (*out.get((r["cik"], r["ratio"]), ()), r["effective"])
    return out


def date_span(d: str) -> tuple[date, date]:
    """The first and last day a YYYY, YYYY-MM or YYYY-MM-DD date covers."""
    parts = [int(x) for x in d.split("-")]
    if len(parts) == 3:
        x = date(*parts)
        return x, x
    if len(parts) == 2:
        y, m = parts
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        return date(y, m, 1), date.fromordinal(nxt.toordinal() - 1)
    return date(parts[0], 1, 1), date(parts[0], 12, 31)


def date_label(d: str) -> str:
    """ "June 2024" for a day or a month; the year alone for a year."""
    first, _ = date_span(d)
    return first.strftime("%B %Y") if d.count("-") >= 1 else str(first.year)


def split_breaks(values: dict[str, list[float | None]], keys: list[str], confirm=None,
                 forced: list[tuple[int, str]] | None = None,
                 one_filing: set[int] | None = None,
                 reviewed_only: bool = False) -> dict[str, dict]:  # fmt: skip
    """Where adjacent columns mix share bases: a later filing restated some years for a stock
    split and the earlier years stay on the pre-split basis (Apple FY2017 5.2B shares, FY2018
    19.8B). Flag only, nothing is adjusted: a share row jumps by a near-whole factor and an EPS
    row moves inversely across the same pair. Returns {metric: {"between": [a, b],
    "ratio_hint": "4:1"}} for each share and EPS row with values on both sides of the latest
    such pair; "1:4" is a reverse split. Older pairs that confirm(between, hint) accepts (NVIDIA:
    4:1 in 2021, then 10:1 in 2024) are listed under "earlier", newest first; confirm may also
    accept a latest pair whose income swing is too large (S-02b). The route's confirm checks the
    reviewed split list. forced [(column index, ratio)] are reviewed splits placed by their dates
    (Alphabet's 20:1 has no share row to detect it; Tesla's 3:1 came with a loss turning to a
    profit); they count whether or not the guard sees them. one_filing: column indices whose
    pair cites the same filing on both sides, never a basis change for the guard. reviewed_only
    (S-02e, the route): only reviewed pairs count; the guard's unreviewed pairs failed a
    hand-check of their note too (7 of 30 no basis change), so they are not shown."""
    found: list[tuple[int, str]] = []
    for i in range(1, len(keys)):
        if one_filing and i in one_filing:
            continue  # S-02d: both columns from one filing are on one share basis
        hit = None
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
                ok = confirm is not None and whole <= SPLIT_MAX_CLEAN_FACTOR \
                    and confirm([keys[i - 1], keys[i]], hint)  # fmt: skip
                if reviewed_only:  # S-02e: an unreviewed pair is not shown at all
                    accept = inverse and ok
                else:
                    accept = inverse and (1 / SPLIT_MAX_INCOME_SWING < swing
                                          < SPLIT_MAX_INCOME_SWING or ok)  # fmt: skip
                if accept:
                    hit = (i, hint)
                    break
            if hit:
                break
        if hit:
            found.append(hit)
    if forced:  # a reviewed split's own ratio wins at its column
        by_i = dict(found) | dict(forced)
        found = sorted(by_i.items())
    if not found:
        return {}
    i, hint = found[-1]
    # older pairs only when the reviewed list confirms them (NVIDIA's 2021 4:1): the guard alone
    # read IPO conversions and mergers as splits and got reverse-split ratios wrong (hand-check of
    # 30 earlier pairs, 2026-11-24: 2 right)
    earlier = [{"between": [keys[j - 1], keys[j]], "ratio_hint": h}
               for j, h in reversed(found[:-1])
               if confirm is not None and confirm([keys[j - 1], keys[j]], h)]  # fmt: skip
    out = {}
    for m in SHARE_ROWS + EPS_ROWS:
        a, b = (values.get(m) or [None] * len(keys))[i - 1 : i + 1]
        if a and b:
            out[m] = {"between": [keys[i - 1], keys[i]], "ratio_hint": hint}
            if earlier:
                out[m]["earlier"] = earlier
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
    any_row = next(iter(by_metric.values()), None)
    if any_row is None:
        return {}
    cols = [c.column if c else None for c in any_row.cells]
    for r in by_metric.values():  # the column labels, from any row that has them
        cols = [a or (c.column if c else None) for a, c in zip(cols, r.cells, strict=False)]

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

    def confirmed(brk_: dict):
        """(cut, factor, evidence) when a filing restates a period before this break by its
        ratio; None otherwise."""
        old_key = brk_["between"][0]
        if old_key not in cols:
            return None
        cut = cols.index(old_key)  # columns 0..cut are on the older share basis
        a, b = brk_["ratio_hint"].split(":")
        expected = int(a) / int(b)  # the break's own split; 3:2 (S-02d) is 1.5 new per old
        whole_ratio = int(a) == 1 or int(b) == 1
        for metric in EPS_ROWS + SHARE_ROWS:
            row = by_metric.get(metric)
            # the first new-basis year (Apple FY2018: 11.91 as filed, 2.98 restated) and then
            # the old-basis years, newest first; an older split (Apple 7:1, 2014) is not this one
            for cell in reversed(row.cells[: cut + 2]) if row else []:
                if cell is None:
                    continue
                facts = reported(metric, cell)
                for later in facts[1:]:
                    if later.filed_date > facts[0].filed_date and facts[0].value and later.value:
                        if whole_ratio:
                            f = share_factor(metric, facts[0], later)
                            ok = f and abs(f / expected - 1) < 1e-9  # the restatement is this
                        else:  # a fractional split: the restated value within 5% of the ratio
                            r = float(later.value) / float(facts[0].value)
                            r = 1 / r if metric in EPS_ROWS else r
                            ok = r > 0 and abs(r / expected - 1) < 0.05
                        if ok:
                            return cut, expected, (metric, cell, facts[0], later)
        return None

    brk = next(iter(breaks.values()))
    newest = confirmed(brk)
    if not newest:
        return {}
    # S-02b: older splits compound (NVIDIA FY2019 and before: 4:1 in 2021, then 10:1 in 2024,
    # so 40 shares today per share then); before an older split no filing confirms, no value
    steps, unknown_before = [newest], -1
    for e in brk.get("earlier", []):
        got = confirmed(e)
        if got is None:
            unknown_before = cols.index(e["between"][0]) if e["between"][0] in cols else -1
            break
        steps.append(got)

    def source_of(step) -> dict:
        _, _, (metric, cell, orig, later) = step
        return {
            "accession_number": later.accession_number, "form": later.form_type,
            "filed_date": later.filed_date.isoformat(), "source_url": later.source_url,
            "evidence": f"{metric} for the period ending {cell.period_end.isoformat()}: "
            f"{float(orig.value):g} as filed {orig.filed_date.isoformat()}, "
            f"{float(later.value):g} in the {later.form_type} filed "
            f"{later.filed_date.isoformat()}",
        }  # fmt: skip

    def ratio_of(f: float) -> str:
        from fractions import Fraction

        q = Fraction(f).limit_denominator(1000)
        return f"{q.numerator}:{q.denominator}"

    factor = newest[1]
    ratio, source = ratio_of(factor), source_of(newest)
    earlier_out = [{"ratio": ratio_of(st_[1]), "before": cols[st_[0] + 1],
                    "source": source_of(st_)} for st_ in steps[1:]]  # fmt: skip
    out = {}

    def factor_at(i: int) -> float:
        out_ = 1.0
        for cut_, f_, _ in steps:
            if i <= cut_:
                out_ *= f_
        return out_

    cut = newest[0]
    for m, row in by_metric.items():
        values = []
        for i, c in enumerate(row.cells):
            if c is None or i > cut:
                values.append(c.value if c else None)
                continue
            if i <= unknown_before:
                values.append(None)
                continue
            f_i = factor_at(i)
            v = float(c.value)
            new = v * f_i if m in SHARE_ROWS else v / f_i
            # a later filing's own restated value wins when it agrees with the ratio
            again = [float(f.value) for f in reported(m, c)[1:] if f.value]
            match = next((x for x in reversed(again) if new and abs(x / new - 1) < 0.02), None)
            values.append(round(match if match is not None else new, 6))
        out[m] = {"ratio": ratio, "derived": True, "values": values, "source": source,
                  "basis": "Before the split: a later filing's restated value where it gives "
                  "one, else the as-filed value adjusted by the ratio the filings "
                  "show."}  # fmt: skip
        if earlier_out:  # S-02b: older splits, compounded into the values before them
            out[m]["earlier"] = earlier_out
    return out


@lru_cache(maxsize=1)
def dated_splits() -> dict[str, list[dict]]:
    """{cik: [{first, last, factor, hint, date, form, filed, disclosure}]}: reviewed splits with
    an effective day or month, oldest first. factor is new shares per old share (2:1 is 2.0,
    1:10 is 0.1, 3:2 is 1.5)."""
    out: dict[str, list[dict]] = {}
    with REVIEWED_SPLITS.open(newline="") as f:
        for r in csv.DictReader(f):
            if not r["effective"] or r["effective"].count("-") < 1:
                continue
            first, last = date_span(r["effective"])
            a, b = r["ratio"].split(":")
            out.setdefault(r["cik"], []).append({
                "first": first, "last": last, "factor": int(a) / int(b), "hint": r["ratio"],
                "date": r["effective"], "form": r["form"], "filed": r["filed"],
                "disclosure": r["disclosure"],
            })  # fmt: skip
    for v in out.values():
        v.sort(key=lambda s: s["first"])
    return out


def cell_bases(rows: dict[str, list], splits: list[dict]) -> tuple[dict[str, list], list]:
    """Q-statements (2026-11-25): the share basis of each share and EPS cell, from the date of
    the filing it cites. A filing made before a split's effective date reports on the pre-split
    basis; one made after it on the post-split basis (a split after the period end is applied
    retroactively in statements issued after it). Only splits that some cell here was filed
    after count. rows: {metric: [cell or None]}, cells with filed_date. Returns ({metric:
    [basis, ...]}, the splits counted), basis being how many counted splits the cell's filing
    came after (len(splits) is the newest basis), None for no cell and -1 for a filing made
    within a split's month; ({}, []) when every cell is on one basis. Per column, not per
    filing: Monster Beverage's quarterly view has Q3 2025 restated for its August 2026 2:1
    split and Q1 and Q2 2026 as filed before it."""
    counted = [s for s in splits
               if any(c is not None and c.filed_date and c.filed_date > s["last"]
                      for cells in rows.values() for c in cells)]  # fmt: skip
    if not counted:
        return {}, []
    out: dict[str, list] = {}
    for m, cells in rows.items():
        out[m] = []
        for c in cells:
            filed = c.filed_date if c is not None else None
            if c is None:
                out[m].append(None)
            elif filed is None or any(s["first"] <= filed <= s["last"] for s in counted):
                out[m].append(-1)
            else:
                out[m].append(sum(1 for s in counted if s["last"] < filed))
    newest = len(counted)
    if not any(b is not None and 0 <= b < newest for v in out.values() for b in v):
        return {}, []
    return out, counted


def factor_of(basis: int, splits: list[dict]) -> float:
    """New shares (on the newest basis) per share on this basis."""
    f = 1.0
    for s in splits[basis:]:
        f *= s["factor"]
    return f


def ratio_text(f: float) -> str:
    """2.0 as "2:1", 0.1 as "1:10", 1.5 as "3:2"."""
    from fractions import Fraction

    q = Fraction(f).limit_denominator(1000)
    return f"{q.numerator}:{q.denominator}"


def basis_breaks(bases: dict[str, list], labels: list[str], splits: list[dict]) -> dict:
    """split_break per row from cell_bases: `between` is the latest pair of adjacent reported
    columns where the basis moves to a later split (older column first), `earlier` the pairs for
    older splits, newest first, and `pre_split_columns` every column on an earlier basis than
    the newest (they need not come first: a later filing restates only the periods it shows
    again)."""
    out = {}
    newest = len(splits)
    for m, bl in bases.items():
        known = [(i, b) for i, b in enumerate(bl) if b is not None and b >= 0]
        named: set[int] = set()
        found = []
        for (i, a), (j, b) in reversed(list(zip(known, known[1:], strict=False))):
            new = [k for k in range(min(a, b), max(a, b)) if k not in named]
            if not new:
                continue
            named.update(new)
            one = splits[new[-1]]["date"] if len(new) == 1 else None
            hint = ratio_text(factor_of(new[0], splits[: new[-1] + 1]))
            found.append({"between": [labels[i], labels[j]], "split_date": one,
                          "ratio_hint": hint, "_at": j})  # fmt: skip
        if found:
            cut = found[0]["_at"]  # by position: two columns can share a label
            # in order: the columns before the break are exactly the ones on an earlier basis
            in_order = all((b < newest) == (i < cut) for i, b in known)
            for f in found:
                f.pop("_at")
            out[m] = {**found[0], **({"earlier": found[1:]} if found[1:] else {}),
                      "in_order": in_order,
                      "pre_split_columns": [labels[i] for i, b in known if b < newest]}  # fmt: skip
    return out


def basis_adjusted(db, cik: str, rows: list, bases: dict[str, list], splits: list[dict],
                   brk: dict, as_of=None) -> dict[str, dict]:  # fmt: skip
    """split_adjusted from cell_bases: each cell on an earlier basis is a later filing's restated
    value where one agrees with its ratio within 2%, else the as-filed value times the ratio
    (divided, for EPS); a cell filed within its split's month has no value. source is the first
    filing found restating a figure by the newest split's ratio, else the reviewed split's own
    filing quote (app/data/splits_reviewed.csv)."""
    from app.db.models import FinancialFact

    def quoted(s: dict) -> dict:
        return {"accession_number": None, "form": s["form"], "filed_date": s["filed"],
                "source_url": None, "evidence": s["disclosure"]}  # fmt: skip

    found_source = _restatement(db, cik, rows, bases, splits, as_of)
    out = {}
    for row in rows:
        bl = bases.get(row.metric)
        if row.derived or bl is None:
            continue
        values = []
        for c, b in zip(row.cells, bl, strict=False):
            if c is None or b is None or b < 0:
                values.append(None)
                continue
            f = factor_of(b, splits)
            if f == 1.0:
                values.append(c.value)
                continue
            v = float(c.value)
            new = v * f if row.metric in SHARE_ROWS else v / f
            q = select(FinancialFact).where(
                FinancialFact.cik == (c.registrant_cik or cik), FinancialFact.metric == row.metric,
                FinancialFact.period_end == c.period_end,
                FinancialFact.period_start == c.period_start, FinancialFact.derived.is_(False),
                FinancialFact.value.is_not(None),
                FinancialFact.filed_date > c.filed_date)  # fmt: skip
            if as_of:
                q = q.where(FinancialFact.filed_date <= as_of)
            again = list(db.scalars(q.order_by(FinancialFact.filed_date)))
            match = next((x for x in again if new and abs(float(x.value) / new - 1) < 0.02), None)
            values.append(round(float(match.value) if match is not None else new, 6))
        out[row.metric] = {
            "ratio": splits[-1]["hint"], "derived": True, "values": values,
            "basis": "Before the split (each figure filed before it): a later filing's restated "
            "value where it gives one, else the as-filed value adjusted by the split's ratio.",
        }  # fmt: skip
        # older splits the statement shows a break for, each with the first column after it
        before = {e["split_date"]: e["between"][1] for e in brk.get("earlier", [])}
        earlier = [{"ratio": s["hint"], "before": before[s["date"]], "source": quoted(s)}
                   for s in reversed(splits[:-1]) if s["date"] in before]  # fmt: skip
        if earlier:
            out[row.metric]["earlier"] = earlier
    for v in out.values():
        v["source"] = found_source or quoted(splits[-1])
    return out


def _restatement(db, cik: str, rows: list, bases: dict[str, list], splits: list[dict],
                 as_of=None) -> dict | None:  # fmt: skip
    """The first filing found restating a shown period by the newest split's ratio (Apple FY2018
    diluted EPS 11.91 as filed, 2.98 in the 10-K filed 2020-10-30): EPS rows first, newest
    columns first. None when no filing here does."""
    from app.db.models import FinancialFact

    s = splits[-1]
    before = splits[-2]["last"] if len(splits) > 1 else date.min
    by_metric = {r.metric: r for r in rows if not r.derived and r.metric in bases}
    for metric in EPS_ROWS + SHARE_ROWS:
        row = by_metric.get(metric)
        for c in reversed(row.cells) if row else []:
            if c is None:
                continue
            q = select(FinancialFact).where(
                FinancialFact.cik == (c.registrant_cik or cik), FinancialFact.metric == metric,
                FinancialFact.period_end == c.period_end,
                FinancialFact.period_start == c.period_start, FinancialFact.derived.is_(False),
                FinancialFact.value.is_not(None), FinancialFact.value != 0)  # fmt: skip
            if as_of:
                q = q.where(FinancialFact.filed_date <= as_of)
            facts = list(db.scalars(q.order_by(FinancialFact.filed_date)))
            olds = [f for f in facts if before < f.filed_date < s["first"]]
            news = [f for f in facts if f.filed_date > s["last"]]
            for orig in olds:
                for later in news:
                    r = float(later.value) / float(orig.value)
                    r = 1 / r if metric in EPS_ROWS else r
                    if r > 0 and abs(r / s["factor"] - 1) < 0.02:
                        return {
                            "accession_number": later.accession_number, "form": later.form_type,
                            "filed_date": later.filed_date.isoformat(),
                            "source_url": later.source_url,
                            "evidence": f"{metric} for the period ending "
                            f"{c.period_end.isoformat()}: {float(orig.value):g} as filed "
                            f"{orig.filed_date.isoformat()}, {float(later.value):g} in the "
                            f"{later.form_type} filed {later.filed_date.isoformat()}",
                        }  # fmt: skip
    return None
