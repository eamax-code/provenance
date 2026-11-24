"""S-06: EPS that does not reconcile with the same filing's net income over weighted shares.

Some filers tag EPS in cents as if it were the main unit (Rio Tinto's 20-F: 2017 diluted EPS
486.9 "USD/shares", its net income over diluted shares $4.87). Nothing is rescaled and no
corrected value is made: the fact keeps its value as filed, and its quality_status says it does
not add up, so every derived use (payout, ratios, screens, marts, chat) leaves it out, as they
leave out anything not "ok" or "partial".

The test is the filing's own figures, never a guess from magnitude: EPS divided by (net income
/ weighted shares) for the same filing, period and currency, within 5% of 100 ("unit_doubtful":
probably cents or pence tagged as the main unit; 30 of 30 checked were). Everything else is left
alone: two-class EPS, preferred dividends, rounding, and the ratios near 1,000 or 1/100, where
the filing usually prints the EPS right and the share count or net income is the figure off (and
Fannie Mae's $0.01 after senior preferred dividends lands near 1/100 by coincidence).
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


def find(db: Session, ciks: list[str] | None = None) -> list[dict]:
    """Every EPS observation about 100 times its same-filing net income over weighted shares."""
    e, n, sh = aliased(FinancialFact), aliased(FinancialFact), aliased(FinancialFact)
    same = lambda o: and_(o.cik == e.cik, o.accession_number == e.accession_number,  # noqa: E731
                          o.period_class == e.period_class, o.period_end == e.period_end,
                          o.period_start.is_not_distinct_from(e.period_start))  # fmt: skip
    shares_metric = case((e.metric == "eps_diluted", PAIRS["eps_diluted"]),
                         else_=PAIRS["eps_basic"])  # fmt: skip
    q = (select(e.id, e.cik, e.accession_number, e.metric, e.period_end, e.unit, e.value,
                e.quality_status, n.value, n.unit, sh.value, sh.id)
         .join(n, and_(same(n), n.metric == "net_income", n.value != 0))
         .join(sh, and_(same(sh), sh.metric == shares_metric, sh.value > 0))
         .where(e.metric.in_(tuple(PAIRS)), e.value != 0,
                e.accession_number.is_not(None)))  # fmt: skip
    if ciks:
        q = q.where(e.cik.in_(ciks))
    out, seen = [], set()
    for (fid, cik, acc, metric, end, unit, eps, status, ni, ni_unit, shares,
         shares_id) in db.execute(q):  # fmt: skip
        if fid in seen or ni_unit != unit.split("/")[0]:  # one currency; one pair per fact
            continue
        ratio = float(eps) / (float(ni) / float(shares))
        if not cents_as_units(ratio):
            continue
        seen.add(fid)
        out.append({"id": fid, "cik": cik, "accession_number": acc, "metric": metric,
                    "period_end": end, "eps": float(eps), "net_income": float(ni),
                    "shares": float(shares), "shares_id": shares_id, "ratio": ratio,
                    "status": UNIT_DOUBTFUL, "was": status})  # fmt: skip
    return out


def apply(db: Session, ciks: list[str] | None = None, found: list[dict] | None = None) -> int:
    """Set the status on each found EPS fact (never on the shares or net income). Returns how
    many changed. Only "ok" or "partial" facts are flagged; a fact already flagged stays."""
    ids = [f["id"] for f in (find(db, ciks) if found is None else found)
           if f["was"] in ("ok", "partial")]  # fmt: skip
    for k in range(0, len(ids), 1000):
        db.execute(update(FinancialFact).where(FinancialFact.id.in_(ids[k:k + 1000]))
                   .values(quality_status=UNIT_DOUBTFUL))  # fmt: skip
    return len(ids)


NOTE = ("EPS as filed is about 100 times net income over weighted shares in the same filing: "
        "probably cents or pence tagged as the main unit. Shown as filed; left out of ratios "
        "and screens.")  # fmt: skip
