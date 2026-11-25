"""Q-04: dividends declared per share by period (docs/contracts/dividends.md).

Values come from dividend_facts (the same normalizer, columns and quality flags as
financial_facts) and are picked by the statements' own selection (`_select_latest`), labelled by
the statements' own period functions and split-adjusted by the statements' per-column rule, so a
dividend column is the income statement's column for the same period. Information, not signals:
no yield until prices exist (P-01).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, DividendFact, FinancialFact
from app.services import eps_reconcile, periods, statements, successions
from app.services.fact_normalizer import (
    DIVIDEND_BASIS,
    PAYOUT_BASES,
    NormalizedFact,
    currency_from_unit,
    derive_quarters,
)
from app.services.notes import dev
from app.services.point_in_time import known_by

METRIC = "dividends_per_share"
# Q-04 gate (2026-11-25): the special flag read from amounts was right on 1 of 7 flags across
# two random samples of 30 companies (cuts, first years and reverse splits look like spikes), so
# it is not given until a better source exists; the code stays for that check
SPECIAL_ENABLED = False
SPECIAL_NOTE = dev("special is not given yet: read from the amounts alone it was right on 1 of 7 "
                   "flags in a check against the filings; it is null on every row.")  # fmt: skip
SPECIAL_RATIO = 2.5  # a quarter this many times the median of the others nearby
SPECIAL_MIN_OTHERS = 4
SPECIAL_DAYS = 365  # "the two years around it": a year either side
SPECIAL_YEAR_DAYS = 2 * 366  # an annual total against the other years two either side
SPECIAL_MIN_YEARS = 2
SPECIAL_BASIS = (
    "Read from the amounts, not the company's label: this quarter's declared dividend per share "
    "is at least 2.5 times the median of the company's other declared quarters within a year "
    "either side (four or more, compared on today's share basis) and 2.5 times both the quarter "
    "before and the quarter after. amount_above_regular is the "
    "excess over that median, per share."
)
# S-06: outside these, the two per-share figures as filed are not on one basis (EPS tagged in
# cents as dollars, Rio Tinto 2016-17: 0.0048; per-share figures of two share classes: 836)
PAYOUT_MIN = 0.01
PAYOUT_MAX = 10
PAYOUT_BASIS = ("declared dividends per share / diluted EPS, same fiscal year, both as reported "
                "in the same filing (one share basis)")  # fmt: skip
ANNUAL_BASIS = (
    "Read from the amounts, not the company's label: this year's declared dividends per share "
    "are at least 2.5 times the median of the company's other years within two years either "
    "side (two or more, compared on today's share basis) and 2.5 times both the year before and "
    "the year after, so a special dividend is likely inside "
    "it; amount_above_regular is the excess over that median, per share."
)
EMPTY_NOTE = ("No dividends per share are reported in the 10-K and 10-Q XBRL filings stored here "
              "for this company.")  # fmt: skip


YEAR_DAYS = (350, 378)  # four quarters: a 52- or 53-week year, or a calendar year
QUARTER_DAYS = (77, 119)  # a 13-week quarter, or a retailer's 16-week fourth (Costco's)
FROM_QUARTERS_NOTE = ("A year marked derived is the sum of its four quarters as filed, given only "
                      "where no annual figure was filed and the quarters are contiguous, of one "
                      "tag, unit and share basis; it has no payout ratio.")  # fmt: skip


SPREAD = 20  # a quarter under 1/20 of the year's largest is a rate, not a quarter (Griffin's)


def _agree(a: float, b: float) -> bool:
    return a == b or (b != 0 and abs(a / b - 1) <= 0.005)


def annual_from_quarters(quarters: dict, factor: dict, year_ends, annual_ends,
                         seen: dict | None = None) -> dict:  # fmt: skip
    """Q-04c(2): {year end: {"fact", "inputs", "factor"}} for each own fiscal year with no
    annual figure, as the sum of four reported quarters: contiguous (each starting the day after
    the last ended, within a few days), together a year long, of one tag and unit, ok or partial,
    and on one share basis (one split factor). Never from three, never across a split. seen:
    {(tag, unit, start, end): values every filing reports}; a quarter two filings give
    differently is never summed (a split restates it: Insperity's 2017; a later filing dates
    another year's dividend to it: Terex's Q2 2020, Corebridge's Q1 2024). Nor is a year with a
    daily rate tagged as a quarter: a nonzero quarter under 1/20 of the year's largest
    (Griffin's), or under $0.01 with more than four decimals (RREEF's 0.001836; Radian's 0.0025
    a quarter is a dividend)."""
    from types import SimpleNamespace

    out: dict = {}
    for y in year_ends:
        if any(abs((y - a).days) <= 7 for a in annual_ends):
            continue
        last = [e for e in quarters if abs((e - y).days) <= 7]
        if not last:
            continue
        chain = [quarters[min(last, key=lambda e: abs((e - y).days))]]
        while len(chain) < 4:
            start = chain[-1].period_start
            prev = [f for f in quarters.values()
                    if start and 1 <= (start - f.period_end).days <= 4]  # fmt: skip
            if not prev:
                break
            chain.append(max(prev, key=lambda f: f.period_end))
        if len(chain) < 4:
            continue
        chain.reverse()
        first, fourth = chain[0], chain[-1]
        span = (fourth.period_end - first.period_start).days + 1
        facs = {factor.get(f.period_end) for f in chain}
        nonzero = [abs(float(f.value)) for f in chain if f.value]
        if any(not all(_agree(float(v), float(f.value)) for v in (seen or {}).get(
                (f.source_tag, f.unit, f.period_start, f.period_end), ()))
               for f in chain if f.value is not None):  # fmt: skip
            continue
        if nonzero and min(nonzero) * SPREAD < max(nonzero):
            continue
        if any(v < 0.01 and round(v, 4) != v for v in nonzero):
            continue
        if (not YEAR_DAYS[0] <= span <= YEAR_DAYS[1]
                or len({f.source_tag for f in chain}) != 1 or len({f.unit for f in chain}) != 1
                or any(f.value is None or f.quality_status not in ("ok", "partial") for f in chain)
                or len(facs) != 1 or None in facs):  # fmt: skip
            continue
        fact = SimpleNamespace(
            value=sum(f.value for f in chain), unit=fourth.unit, source_tag=fourth.source_tag,
            quality_status="derived", period_start=first.period_start,
            period_end=fourth.period_end, accession_number=fourth.accession_number,
            form_type=fourth.form_type, filed_date=fourth.filed_date,
            source_url=fourth.source_url, cik=fourth.cik)  # fmt: skip
        out[fourth.period_end] = {"fact": fact, "inputs": chain, "factor": facs.pop()}
    return out


def _cite(f) -> dict:
    return {"accession_number": f.accession_number, "form": f.form_type,
            "filed_date": f.filed_date.isoformat() if f.filed_date else None,
            "source_url": f.source_url}  # fmt: skip


def _pick(rows: list, cik: str, currency: str | None) -> dict[date, object]:
    """One fact per period end, as the statements choose: the statements' selection
    (`_select_latest`), then the company's own filing and its reporting currency first."""
    from app.api.routes_companies import _select_latest

    chosen = _select_latest(rows)
    out: dict[date, object] = {}
    for f in sorted(chosen, key=lambda f: (f.cik != cik, f.unit != currency, f.unit)):
        out.setdefault(f.period_end, f)
    return out


def build(db: Session, company: Company, period: str = "annual", n: int | None = None,
          as_of: date | None = None) -> dict:  # fmt: skip
    from app.api.routes_companies import _row_to_normalized
    from app.db.models import MartCompany

    cik, fye, conv = company.cik, company.fiscal_year_end, periods.convention(company)
    ciks = [cik] + [p.predecessor_cik for p in successions.predecessors(db, cik)]
    q = select(DividendFact).where(DividendFact.cik.in_(ciks), DividendFact.metric == METRIC,
                                   DividendFact.derived.is_(False))  # fmt: skip
    if as_of:
        q = known_by(q, as_of, model=DividendFact)
    # durations with a start only: a dividend dated by its declaration alone is no fiscal period
    # (one mortgage REIT tagged each declaration, eight "FY2022" rows)
    rows = [r for r in db.scalars(q) if r.period_start is not None]
    mart = db.get(MartCompany, cik)
    currency = mart.reporting_currency if mart else None
    notes: list[str] = []
    if not rows:
        return {"currency": currency, "data": [], "splits": [], "notes": [EMPTY_NOTE]}
    dated = statements.dated_splits().get(cik, [])

    def straddles(a, b) -> bool:
        lo, hi = sorted(d for d in (a, b) if d)
        return any(lo < s["first"] and hi > s["last"] for s in dated) if lo and hi else False

    # quarters: reported, plus derived (FY minus nine months, YTD minus YTD) on one share basis
    quarters = _pick([r for r in rows if r.period_class == "quarterly"], cik, currency)
    derived: dict[date, dict] = {}
    # each period as first filed, so a derived quarter's two inputs come from one reporting cycle
    # (a later 10-K restating a year after an unreviewed split gave FY 0.58 against nine months
    # 0.87 as first filed: -0.29)
    first: dict[tuple, DividendFact] = {}
    for r in rows:
        if r.period_type == "duration" and r.quality_status in ("ok", "partial"):
            k = (r.source_tag, r.unit, r.period_start, r.period_end)
            if k not in first or (r.filed_date or date.max) < (first[k].filed_date or date.max):
                first[k] = r
    nfs = [_row_to_normalized(r) for r in first.values()]
    for d in derive_quarters([x for x in nfs if isinstance(x, NormalizedFact)]):
        if d.period_end in quarters or d.period_end in derived:
            continue
        mi, su = d.derivation["minuend"], d.derivation["subtrahend"]
        filed = [date.fromisoformat(x["filed_date"]) if x["filed_date"] else None for x in (mi, su)]
        if d.value is not None and d.value < 0:
            q4 = periods.label(d.period_end, "quarterly", conv)
            notes.append(f"{q4}: not derived, the year less nine months is negative.")
            continue
        if straddles(*filed):
            q4 = periods.label(d.period_end, "quarterly", conv)
            notes.append(f"{q4}: not derived, its "
                         "inputs were filed on either side of a stock split.")  # fmt: skip
            continue
        derived[d.period_end] = {"fact": d, "inputs": [mi, su]}
    annual = _pick([r for r in rows if r.period_class == "annual"], cik, currency)

    def cell(end: date, cls: str):
        if cls == "annual":
            f = annual.get(end)
            if f is None and end in from_q:
                return from_q[end]["fact"], from_q[end]["inputs"]
            return (f, None) if f else (None, None)
        if end in quarters:
            return quarters[end], None
        d = derived.get(end)
        return (d["fact"], d["inputs"]) if d else (None, None)

    # split basis per cell, from the date of the filing it cites (the statements' rule)
    def factors(cells: dict[date, object]) -> dict[date, float | None]:
        if not dated:
            return {e: 1.0 for e in cells}
        ends = sorted(cells)
        bases, counted = statements.cell_bases({METRIC: [cells[e] for e in ends]}, dated)
        if not bases:
            return {e: 1.0 for e in ends}
        out = {}
        for e, b in zip(ends, bases[METRIC], strict=True):
            out[e] = None if b is None or b < 0 else statements.factor_of(b, counted)
        return out

    q_cells = {e: cell(e, "quarterly")[0] for e in set(quarters) | set(derived)}
    q_factor = factors(q_cells)
    # Q-04c(2): a year with no annual figure, as the sum of its four quarters, each as first
    # filed (a later filing can date another year's dividends to it: Houlihan Lokey's FY2019
    # 10-K gives FY2018's quarters as 0.27 and 0.31 against 0.20 in its own year's 10-K), on the
    # share basis of those filings
    as_first = [r for r in first.values() if r.period_class == "quarterly" or (
        r.period_class == "other"
        and QUARTER_DAYS[0] <= (r.period_end - r.period_start).days + 1 <= QUARTER_DAYS[1])]
    reported = _pick(as_first, cik, currency)
    seen: dict = {}
    for r in rows:
        if r.quality_status in ("ok", "partial") and r.value is not None:
            seen.setdefault((r.source_tag, r.unit, r.period_start, r.period_end),
                            set()).add(r.value)  # fmt: skip
    from_q = annual_from_quarters(reported, factors(reported),
                                  periods.parse_year_ends(company.fiscal_year_ends), annual, seen)
    special_q = _specials(q_cells, q_factor)
    a_cells = {e: f for e, f in annual.items()}
    special_a = _specials(a_cells, factors(a_cells), SPECIAL_YEAR_DAYS, SPECIAL_MIN_YEARS,
                          ANNUAL_BASIS)  # fmt: skip

    cls = "annual" if period == "annual" else "quarterly"
    ends = sorted(set(annual) | set(from_q)) if cls == "annual" else sorted(q_cells)
    ends = ends[-(n or (10 if cls == "annual" else 20)):]
    cells = {e: cell(e, cls)[0] for e in ends if e not in from_q or cls != "annual"}
    fac = factors(cells) if cls == "annual" else {e: q_factor.get(e) for e in ends}
    if cls == "annual":
        fac.update({e: from_q[e]["factor"] for e in ends if e in from_q})
    eps = _same_filing_eps(db, ciks, list(cells.values())) if cls == "annual" else {}
    paid = _picked_metric(db, ciks, cik, currency, "dividends_paid", cls, as_of)
    data = []
    for e in ends:
        f, inputs = cell(e, cls)
        value = float(f.value) if f.value is not None else None
        factor = fac.get(e)
        start = f.period_start
        row = {
            "period_label": periods.label(e, cls, conv),
            "period_start": start.isoformat() if start else None,
            "period_end": e.isoformat(),
            "period_fiscal_year": periods.fiscal_year(e, conv, period_class=cls),
            "fiscal_year_end": fye,
            "label_basis": periods.label_basis(conv),
            "calendar_period": periods.calendar_period(start, e, cls),
            "declared_per_share": value,
            "unit": f.unit,
            "currency": currency_from_unit(f.unit),
            "basis": DIVIDEND_BASIS.get(f.source_tag, "declared"),
            "basis_tag": DIVIDEND_BASIS.get(f.source_tag, "declared"),
            "quality_status": f.quality_status,
            "derived": bool(inputs),
            "filing": _cite(f),
            "split_adjusted": None if factor is None or value is None else {
                "value": round(value / factor, 6), "factor": factor, "derived": True},
            "special": None,
            "payout_ratio": None,
            "dividends_paid": None,
        }  # fmt: skip
        if inputs and cls == "annual":  # Q-04c(2): the four quarters it sums
            row["inputs"] = [{"period_label": periods.label(x.period_end, "quarterly", conv),
                              "value": float(x.value), "accession_number": x.accession_number,
                              "source_url": x.source_url} for x in inputs]  # fmt: skip
        elif inputs:
            row["inputs"] = [{"period_label": periods.label(date.fromisoformat(x["period_end"]),
                                                            "annual" if i == 0 else "ytd", conv),
                              "value": float(x["value"]), "accession_number": x["accession_number"],
                              "source_url": f.source_url if i == 0 else None}
                             for i, x in enumerate(inputs)]  # fmt: skip
        if not SPECIAL_ENABLED:
            row["special"] = None
        elif cls == "quarterly":
            row["special"] = special_q.get(e)
        else:
            row["special"] = _annual_special(special_q, special_a.get(e), start, e)
        p = paid.get(e)
        if p is not None and p.value is not None:
            row["dividends_paid"] = {"value": float(p.value), "unit": p.unit, **_cite(p)}
        if cls == "annual" and not inputs:
            row["payout_ratio"] = _payout(f, eps.get((f.accession_number, e)))
            if row["payout_ratio"] == IMPLAUSIBLE:
                row["payout_ratio"] = None
                notes.append(f"{row['period_label']}: no payout ratio: the dividend and "
                             "diluted EPS as filed give a ratio below 0.01 or above 10, so they "
                             "are not on one basis (one may be in cents, or for another share "
                             "class); see the filing.")  # fmt: skip
        if factor is None:
            notes.append(f"{row['period_label']}: filed in the month of a split dated only to the "
                         "month: no split-adjusted value.")  # fmt: skip
        data.append(row)
    splits = [{"ratio": s["hint"], "date": s["date"],
               "source": {"form": s["form"], "filed_date": s["filed"],
                          "evidence": s["disclosure"]}} for s in dated]  # fmt: skip
    if cls == "annual" and any(e in from_q for e in ends):
        notes.append(FROM_QUARTERS_NOTE)
    if not SPECIAL_ENABLED:
        notes.append(SPECIAL_NOTE)
    notes[0:0] = ["As reported: each value in the share basis of the filing it cites. "
                  "No yield: prices are not loaded.",
                  dev("split_adjusted puts each value on today's share basis using reviewed "
                      "splits only.")]  # fmt: skip
    return {"currency": currency, "data": data, "splits": splits, "notes": notes}


def _picked_metric(db, ciks, cik, currency, metric, cls, as_of) -> dict:
    q = select(FinancialFact).where(FinancialFact.cik.in_(ciks), FinancialFact.metric == metric,
                                    FinancialFact.period_class == cls,
                                    FinancialFact.derived.is_(False))  # fmt: skip
    if as_of:
        q = known_by(q, as_of)
    return _pick(list(db.scalars(q)), cik, currency)


def _same_filing_eps(db, ciks, cells: list) -> dict:
    """{(accession, period end): diluted EPS} as the filing each dividend cell cites reports it,
    so both sides of the payout ratio sit on one share basis."""
    accs = sorted({c.accession_number for c in cells if c is not None and c.accession_number})
    if not accs:
        return {}
    q = select(FinancialFact).where(FinancialFact.cik.in_(ciks),
                                    FinancialFact.metric == "eps_diluted",
                                    FinancialFact.period_class == "annual",
                                    FinancialFact.derived.is_(False),
                                    FinancialFact.accession_number.in_(accs))  # fmt: skip
    out: dict = {}
    for f in db.scalars(q):
        if f.quality_status in eps_reconcile.STATUSES:
            continue  # S-06: EPS that does not reconcile as filed never makes a payout
        k = (f.accession_number, f.period_end)
        if k not in out or (out[k].quality_status not in ("ok", "partial")
                            and f.quality_status in ("ok", "partial")):  # fmt: skip
            out[k] = f
    return out


IMPLAUSIBLE = "implausible"  # _payout's answer for a ratio outside PAYOUT_MIN..PAYOUT_MAX


def _payout(dps, eps) -> dict | str | None:
    """Declared per share over diluted EPS for the same fiscal year, in one currency; only on a
    declared or recognised basis (never on cash paid or distributions per unit)."""
    if eps is None or eps.value is None or dps.value is None:
        return None
    if DIVIDEND_BASIS.get(dps.source_tag, "declared") not in PAYOUT_BASES:
        return None
    if currency_from_unit(eps.unit) != currency_from_unit(dps.unit) or float(eps.value) <= 0:
        return None
    if eps.accession_number != dps.accession_number:
        return None  # only from the dividend's own filing: one share basis (Toyota's 5:1 split)
    if not PAYOUT_MIN <= float(dps.value) / float(eps.value) <= PAYOUT_MAX:
        return IMPLAUSIBLE
    return {
        "value": round(float(dps.value) / float(eps.value), 4), "derived": True,
        "basis": PAYOUT_BASIS,
        "inputs": [{"metric": METRIC, "value": float(dps.value), **_cite(dps)},
                   {"metric": "eps_diluted", "value": float(eps.value), **_cite(eps)}],
    }  # fmt: skip


def _specials(cells: dict[date, object], factor: dict[date, float | None],
              days: int = SPECIAL_DAYS, least: int = SPECIAL_MIN_OTHERS,
              basis: str = SPECIAL_BASIS) -> dict:  # fmt: skip
    """{period end: special} for each period compared with enough others nearby (quarters: four
    within a year either side; years: two within two years either side), on today's share
    basis; None where there are too few to compare."""
    adj = {e: float(f.value) / factor[e] for e, f in cells.items()
           if f.value is not None and factor.get(e)}  # fmt: skip
    out: dict[date, dict | None] = {}
    for e, v in adj.items():
        others = [x for d, x in adj.items() if d != e and abs((d - e).days) <= days]
        if len(others) < least:
            out[e] = None
            continue
        med = statistics.median(others)
        # a spike, not a step: above the median and above both neighbours (a dividend cut or a
        # first full year read as specials when only the median was asked)
        order = sorted(adj)
        i = order.index(e)
        prev = adj[order[i - 1]] if i > 0 else None
        nxt = adj[order[i + 1]] if i + 1 < len(order) else None
        likely = (med > 0 and v >= SPECIAL_RATIO * med and prev is not None and nxt is not None
                  and v >= SPECIAL_RATIO * prev and v >= SPECIAL_RATIO * nxt)  # fmt: skip
        out[e] = {"likely": likely, "derived": True,
                  "amount_above_regular": round((v - med) * factor[e], 6) if likely else None,
                  **({"basis": basis} if likely else {})}  # fmt: skip
    return out


def _annual_special(special_q: dict, year: dict | None, start: date | None,
                    end: date) -> dict | None:  # fmt: skip
    """An annual period is likely when one of its quarters is (their excess, summed), or when its
    total stands out against the other years (company facts can leave a special out of every
    quarter: Costco's $15.00 is only in FY2024's total)."""
    lo = start or end - timedelta(days=366)
    inside = {e: s for e, s in special_q.items() if lo <= e <= end}
    hits = [s for s in inside.values() if s and s["likely"]]
    if hits:
        return {"likely": True, "derived": True,
                "amount_above_regular": round(sum(s["amount_above_regular"] for s in hits), 6),
                "basis": SPECIAL_BASIS + " An annual period is marked when one of its quarters "
                "is; its excess is the sum of theirs."}  # fmt: skip
    if year is not None and year["likely"]:
        return year
    if year is None and all(s is None for s in inside.values()):
        return None
    return {"likely": False, "derived": True, "amount_above_regular": None}
