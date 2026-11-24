"""Executive pay and pay versus performance (D-10, docs/contracts/executive-pay.md), assembled
from the proxy's tagged Item 402(v) table (proxy_pay_facts). Each fiscal year comes from the
latest proxy filed by as_of that reports it. Values as disclosed in the proxy; nothing is
recomputed. Information, not signals."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Filing, ProxyPayFact
from app.services.sec_client import filing_index_url

DISCLAIMER = "Information, not signals. Not investment advice."
BASIS = ("As disclosed in the proxy: the PEO and the average of the other named executives, as "
         "tagged in the proxy's pay-versus-performance table (Item 402(v)).")  # fmt: skip
NOTES = [
    "Compensation actually paid is the SEC's defined measure (Item 402(v) of Regulation S-K), "
    "not realized or take-home pay.",
    "TSR is the value at each year end of $100 invested at the start of the first year shown, "
    "as the proxy gives it.",
    "The Summary Compensation Table is not tagged, so pay is shown for the PEO and as the "
    "average of the other named executives, not for each executive.",
]
YEAR_FIELDS = ("peo_total_comp", "peo_cap")
ANNUAL = ("10-K", "10-K/A", "10-KT", "10-KT/A")


def month_end(d: date) -> date:
    """The month end nearest to d: the SEC's data sets round each fact's date this way."""
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    end, prev = nxt - timedelta(days=1), date(d.year, d.month, 1) - timedelta(days=1)
    return end if (end - d) <= (d - prev) else prev


def exact_year_ends(db: Session, cik: str, ends, as_of: date | None = None) -> dict[date, date]:
    """D-10b: the data sets round each fiscal year end to the month end (Apple's FY2024 ended
    2024-09-28, tagged 2024-09-30). The company's own annual report gives the exact date: its
    period of report, which EDGAR takes from dei:DocumentPeriodEndDate. A year end with no annual
    report loaded here that rounds to it is left out (shown as the rounded month end)."""
    q = select(Filing.report_date).where(Filing.cik == cik, Filing.form_type.in_(ANNUAL),
                                         Filing.report_date.is_not(None))  # fmt: skip
    if as_of:
        q = q.where(Filing.filing_date <= as_of)
    by_end: dict[date, set[date]] = {}
    for r in set(db.scalars(q)):
        by_end.setdefault(month_end(r), set()).add(r)
    return {e: next(iter(by_end[e])) for e in ends if len(by_end.get(e, ())) == 1}


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def for_company(db: Session, cik: str, as_of: date | None = None) -> dict:
    q = select(ProxyPayFact).where(ProxyPayFact.cik == cik)
    if as_of:
        q = q.where(ProxyPayFact.filing_date <= as_of)
    facts = list(db.scalars(q))
    out = {"cik": cik, "as_of": as_of.isoformat() if as_of else None, "currency": None,
           "proxy": None, "years": [], "measures": [],
           "labels": {"disclaimer": DISCLAIMER, "basis": BASIS}, "notes": NOTES}  # fmt: skip
    if not facts:
        return out
    by_filing: dict[str, list[ProxyPayFact]] = {}
    for f in facts:
        by_filing.setdefault(f.accession_number, []).append(f)
    order = sorted(by_filing, key=lambda a: (by_filing[a][0].filing_date, a), reverse=True)
    urls = dict(db.execute(select(Filing.accession_number, Filing.source_url)
                           .where(Filing.accession_number.in_(order))).all())  # fmt: skip

    def source(acc: str) -> dict:
        f = by_filing[acc][0]
        return {"accession_number": acc, "form": f.form_type,
                "filed_date": f.filing_date.isoformat(),
                "source_url": urls.get(acc) or filing_index_url(cik, acc)}  # fmt: skip

    # each year from the newest proxy that reports it
    year_src: dict[date, str] = {}
    for acc in order:
        for f in by_filing[acc]:
            if f.field in YEAR_FIELDS and f.fiscal_year_end and f.fiscal_year_end not in year_src:
                year_src[f.fiscal_year_end] = acc
    if not year_src:
        return out
    latest = (
        order[0]
        if order[0] in year_src.values()
        else max(set(year_src.values()), key=lambda a: (by_filing[a][0].filing_date, a))
    )
    units = Counter(f.unit for acc in set(year_src.values()) for f in by_filing[acc]
                    if f.field in YEAR_FIELDS and f.unit)  # fmt: skip
    out["currency"] = units.most_common(1)[0][0] if units else None
    out["proxy"] = source(latest)
    exact = exact_year_ends(db, cik, year_src, as_of)
    for fy in sorted(year_src, reverse=True):
        acc = year_src[fy]
        yf = [f for f in by_filing[acc] if f.fiscal_year_end == fy]
        out["years"].append(_year(fy, yf, by_filing[acc], source(acc), exact.get(fy)))
    measures = [f for f in by_filing[latest] if f.field == "measure" and f.value_text]
    measures.sort(key=lambda f: (f.fiscal_year_end or date.min, _measure_rank(f.dims)))
    seen: list[str] = []
    for f in measures:
        if f.value_text not in seen:
            seen.append(f.value_text)
    out["measures"] = seen
    return out


def _measure_rank(dims: str | None) -> tuple:
    for part in (dims or "").split(";"):
        if part.startswith("Measure="):
            v = part.split("=", 1)[1]
            return (0, int(v)) if v.isdigit() else (1, v)
    return (2, "")


def _year(fy: date, facts: list[ProxyPayFact], filing_facts: list[ProxyPayFact],
          src: dict, exact: date | None = None) -> dict:  # fmt: skip
    def one(field, plain_only=True):
        for f in facts:
            if f.field == field and (not plain_only or not f.dims):
                return f
        return None

    names = {f.member: f.value_text for f in facts if f.field == "peo_name" and f.member}
    peo_names = {f.member: f.value_text for f in facts
                 if f.field == "peo_name" and (f.category or "").lower().endswith("peo")
                 and not (f.category or "").startswith("NonPeo")}  # fmt: skip
    plain_name = next((f.value_text for f in facts if f.field == "peo_name" and not f.dims), None)
    people: dict[str | None, dict] = {}
    for f in facts:
        if f.field not in YEAR_FIELDS:
            continue
        if f.category and f.category.startswith("NonPeo"):
            continue
        key = f.member
        p = people.setdefault(key, {"name": None, "total_comp": None, "comp_actually_paid": None})
        p["total_comp" if f.field == "peo_total_comp" else "comp_actually_paid"] = _num(f.value_num)
    if any(k is not None for k in people):  # tagged per person: the untagged total is a sum
        people.pop(None, None)
    for key, p in people.items():
        if key is not None:
            p["name"] = names.get(key)
        elif len(peo_names) == 1:
            p["name"] = next(iter(peo_names.values()))
        else:
            p["name"] = plain_name
    neo_names = [f.value_text for f in facts if f.field == "peo_name"
                 and (f.category or "").startswith("NonPeo") and f.value_text]  # fmt: skip
    csm_value = one("csm_value")
    csm_name = one("csm_name") or next((f for f in filing_facts if f.field == "csm_name"
                                        and not f.dims), None)  # fmt: skip

    def val(field):
        f = one(field)
        return _num(f.value_num) if f else None

    return {
        "fiscal_year_end": (exact or fy).isoformat(),
        "fiscal_year_end_rounded": exact is None,
        "peo": sorted(people.values(), key=lambda p: (p["name"] or "")),
        "neo_average": {"total_comp": val("neo_avg_total_comp"),
                        "comp_actually_paid": val("neo_avg_cap"), "names": neo_names},
        "tsr": val("tsr"), "peer_tsr": val("peer_tsr"), "net_income": val("net_income"),
        "company_selected_measure": {"name": csm_name.value_text if csm_name else None,
                                     "value": _num(csm_value.value_num) if csm_value else None}
        if (csm_value or csm_name) else None,
        "source": src,
    }  # fmt: skip
