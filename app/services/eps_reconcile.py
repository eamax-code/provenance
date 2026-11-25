"""S-06: EPS that does not reconcile with the same filing's net income over weighted shares.

Some filers tag EPS in cents as if it were the main unit (Rio Tinto's 20-F: 2017 diluted EPS
486.9 "USD/shares", its net income over diluted shares $4.87). Nothing is rescaled and no
corrected value is made: the fact keeps its value as filed, and its quality_status says it does
not add up, so every derived use (payout, ratios, screens, marts, chat) leaves it out, as they
leave out anything not "ok" or "partial".

The test is the filing's own figures, never a guess from magnitude: EPS divided by (net income
/ weighted shares) for the same filing, period and currency.
- Within 5% of 100: the EPS is "unit_doubtful" (probably cents or pence tagged as the main unit;
  30 of 30 checked were).
- Within 5% of 1,000 or 1/100 (S-06b): which of the three is off is read from the company's
  other filings for the same period (their comparative columns). A figure is off when no other
  filing agrees with it, every other filing differs from it by about 1,000, 100 or their
  inverses, and putting the other filings' figure in its place alone makes the EPS reconcile;
  when exactly one of the three passes, that fact is "unit_doubtful" (Waters' 59.5 billion
  weighted shares for 59.5 million; Barrett's EPS 1,570 for $1.57; Palatin's net income in
  thousands). Otherwise nothing is flagged: Fannie Mae's $0.01 after senior preferred dividends
  agrees with every filing, and a filing whose only comparison is itself wrong (Landmark Bancorp)
  is left alone.
"""

from __future__ import annotations

from sqlalchemy import and_, case, select, update
from sqlalchemy.orm import Session, aliased

from app.db.models import FinancialFact

UNIT_DOUBTFUL = "unit_doubtful"
STATUSES = (UNIT_DOUBTFUL,)
BAND = 0.05
FACTOR = 100.0
PAIRS = {"eps_diluted": "shares_diluted_weighted", "eps_basic": "shares_basic_weighted"}


def cents_as_units(ratio: float) -> bool:
    """EPS within 5% of 100 times net income over weighted shares."""
    return abs(ratio / FACTOR - 1) <= BAND


def _triples(db: Session, ciks: list[str] | None):
    """(EPS, net income, weighted shares) of one filing and period, in one currency."""
    e, n, sh = aliased(FinancialFact), aliased(FinancialFact), aliased(FinancialFact)
    same = lambda o: and_(o.cik == e.cik, o.accession_number == e.accession_number,  # noqa: E731
                          o.period_class == e.period_class, o.period_end == e.period_end,
                          o.period_start.is_not_distinct_from(e.period_start))  # fmt: skip
    shares_metric = case((e.metric == "eps_diluted", PAIRS["eps_diluted"]),
                         else_=PAIRS["eps_basic"])  # fmt: skip
    q = (select(e.id, e.cik, e.accession_number, e.metric, e.period_start, e.period_end,
                e.unit, e.value, e.quality_status, n.id, n.value, n.unit, n.quality_status,
                sh.id, sh.metric, sh.value, sh.quality_status, e.form_type, e.filed_date)
         .join(n, and_(same(n), n.metric == "net_income", n.value != 0))
         .join(sh, and_(same(sh), sh.metric == shares_metric, sh.value > 0))
         .where(e.metric.in_(tuple(PAIRS)), e.value != 0,
                e.accession_number.is_not(None)))  # fmt: skip
    if ciks:
        q = q.where(e.cik.in_(ciks))
    seen = set()
    for r in db.execute(q):
        if r[0] in seen or r[11] != r[6].split("/")[0]:  # one currency; one pair per fact
            continue
        seen.add(r[0])
        yield r


def _ratio(eps: float, net_income: float, shares: float) -> float:
    return eps / (net_income / shares)


def find(db: Session, ciks: list[str] | None = None) -> list[dict]:
    """Every EPS observation about 100 times its same-filing net income over weighted shares."""
    out = []
    for (fid, cik, acc, metric, _start, end, _unit, eps, status, _nid, ni, _nu, _ns, shares_id,
         _sm, shares, _ss, _form, _filed) in _triples(db, ciks):  # fmt: skip
        ratio = _ratio(float(eps), float(ni), float(shares))
        if not cents_as_units(ratio):
            continue
        out.append({"id": fid, "cik": cik, "accession_number": acc, "metric": metric,
                    "period_end": end, "eps": float(eps), "net_income": float(ni),
                    "shares": float(shares), "shares_id": shares_id, "ratio": ratio,
                    "status": UNIT_DOUBTFUL, "was": status})  # fmt: skip
    return out


def _near(ratio: float, k: float) -> bool:
    return abs(ratio / k - 1) <= BAND


_SCALES = (1000.0, 0.001, 100.0, 0.01)


def _others(db: Session, cik: str, metric: str, unit: str, start, end, acc: str) -> list:
    """(value, form, filed date, accession, source_url) of the same figure in other filings."""
    f = FinancialFact
    return list(db.execute(select(f.value, f.form_type, f.filed_date, f.accession_number,
                                  f.source_url).where(
        f.cik == cik, f.metric == metric, f.unit == unit, f.period_end == end,
        f.period_start.is_not_distinct_from(start), f.accession_number != acc,
        f.value.is_not(None), f.value != 0)))  # fmt: skip


def find_off(db: Session, ciks: list[str] | None = None) -> list[dict]:
    """S-06b: in EPS triples about 1,000 or 1/100 off, the one figure the company's other
    filings show to be off (see the module docstring)."""
    out, seen = [], set()
    for t in _triples(db, ciks):
        (eid, cik, acc, metric, start, end, unit, eps, es, nid, ni, nu, ns, sid, sm, shares,
         ss, form, filed) = t  # fmt: skip
        vals = {"eps": float(eps), "net_income": float(ni), "shares": float(shares)}
        if not (_near(_ratio(**vals), 1000.0) or _near(_ratio(**vals), 0.01)):
            continue
        inputs = (("eps", eid, metric, unit, es), ("net_income", nid, "net_income", nu, ns),
                  ("shares", sid, sm, "shares", ss))  # fmt: skip
        fixes = []
        for name, fid, m, u, was in inputs:
            alts = _others(db, cik, m, u, start, end, acc)
            v = vals[name]
            if not alts or any(abs(v / float(a[0]) - 1) < 0.02 for a in alts):
                continue  # nothing to compare with, or another filing agrees with it
            if not all(any(_near(v / float(a[0]), k) for k in _SCALES) for a in alts):
                continue
            alts.sort(key=lambda a: float(a[0]))
            other = alts[len(alts) // 2]
            tried = {**vals, name: float(other[0])}
            if abs(_ratio(**tried) - 1) <= BAND:
                factor = next(k for k in _SCALES if _near(v / float(other[0]), k))
                fixes.append({"id": fid, "cik": cik, "accession_number": acc, "metric": m,
                              "period_start": start, "period_end": end, "value": v,
                              "factor": factor, "form": form, "filed_date": filed,
                              "other": {"value": float(other[0]), "form": other[1],
                                        "filed_date": other[2], "accession_number": other[3],
                                        "source_url": other[4]},
                              "status": UNIT_DOUBTFUL, "was": was})  # fmt: skip
        if len(fixes) == 1 and fixes[0]["id"] not in seen:
            seen.add(fixes[0]["id"])  # a net income or shares fact can sit in two triples
            out.append(fixes[0])
    return out


_TOO = {
    1000.0: "1,000 times too large",
    100.0: "100 times too large",
    0.001: "1,000 times too small",
    0.01: "100 times too small",
}


def _day(d) -> str:
    return getattr(d, "isoformat", lambda: str(d))()


def scale_note(f: dict, shown: dict | None = None) -> str:
    """The cell note for a figure off by a scale (S-06b), in its direction. `shown`: the agreeing
    filing whose figure the cell shows instead ({form, filed_date}); None when no agreeing
    filing was filed by the date asked, and the cell is blank."""
    v = f"{f['value']:,.4f}".rstrip("0").rstrip(".")
    head = (f"The figure as filed in the {f['form']} of {_day(f['filed_date'])} ({v}) looks to be "
            f"about {_TOO[f['factor']]}")  # fmt: skip
    if shown is not None:
        return f"{head}; shown as reported in the {shown['form']} of {_day(shown['filed_date'])}."
    return (
        f"{head} (other filings for the period disagree with it by that scale); no agreeing "
        "filing had been filed by the date asked, so no figure is shown."
    )


def apply(db: Session, ciks: list[str] | None = None, found: list[dict] | None = None) -> int:
    """Set the status on each found fact. Returns how many changed. Only "ok" or "partial"
    facts are flagged; a fact already flagged stays."""
    if found is None:
        found = find(db, ciks) + find_off(db, ciks)
    ids = sorted({f["id"] for f in found if f["was"] in ("ok", "partial")})
    for k in range(0, len(ids), 1000):
        db.execute(update(FinancialFact).where(FinancialFact.id.in_(ids[k:k + 1000]))
                   .values(quality_status=UNIT_DOUBTFUL))  # fmt: skip
    return len(ids)


NOTE = ("EPS as filed is about 100 times net income over weighted shares in the same filing: "
        "probably cents or pence tagged as the main unit. Shown as filed; left out of ratios "
        "and screens.")  # fmt: skip
