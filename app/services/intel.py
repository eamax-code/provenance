"""Company intelligence brief: a deterministic, cited summary that the chat model phrases.

Every number and claim in the brief comes from stored SEC data and carries a citation number
pointing at the SEC record. The language model sees only this context (see routes_chat).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, FinancialFact
from app.services.company_lookup import search_companies
from app.services.form8k import ITEM_TITLES, LEADERSHIP_ITEM, split_items
from app.services.point_in_time import known_by

METRIC_LABELS = {
    "revenue": "Revenue",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "operating_cash_flow": "Operating cash flow",
}
_STOP = {
    "the", "a", "an", "of", "for", "and", "or", "in", "on", "is", "are", "was", "what", "how",
    "who", "tell", "me", "about", "show", "give", "company", "inc", "corp", "its", "their",
    "revenue", "growth", "cfo", "ceo", "filings", "latest", "did", "does", "do", "has", "have",
}  # fmt: skip


@dataclass
class Brief:
    company: Company
    as_of: date | None
    metrics: list[dict] = field(default_factory=list)
    filings: list[dict] = field(default_factory=list)
    leadership_filings: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)

    def cite(self, label: str, url: str) -> int:
        self.citations.append({"n": len(self.citations) + 1, "label": label, "url": url})
        return len(self.citations)

    def context(self) -> str:
        return "\n".join(self.context_lines)


def resolve_company(db: Session, text: str) -> Company | None:
    """Find the company a free-text question is about: ticker or CIK first, then names."""
    text = re.sub(r"['\u2019]s\b", "", text)  # "Apple's" -> "Apple"
    words = [w.rstrip(".") for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.&-]*", text)]
    for w in words:
        if w.isdigit() and len(w) <= 10 or (w.isupper() and 1 <= len(w) <= 6):
            hits, _ = search_companies(db, w, limit=1)
            if hits and hits[0].match_type in ("cik", "ticker"):
                return hits[0].company
    useful = [w for w in words if w.lower() not in _STOP]
    for size in (3, 2, 1):
        for i in range(len(useful) - size + 1):
            phrase = " ".join(useful[i : i + size])
            if len(phrase) < 3:
                continue
            hits, _ = search_companies(db, phrase, limit=1)
            if hits and hits[0].match_type in ("ticker", "name_exact", "name_prefix"):
                return hits[0].company
    return None


def _money(v: Decimal | float) -> str:
    x = float(v)
    for div, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(x) >= div:
            return f"${x / div:,.1f} {word}"
    return f"${x:,.0f}"


def _annual_series(db: Session, cik: str, metric: str, as_of: date | None) -> list[FinancialFact]:
    stmt = select(FinancialFact).where(
        FinancialFact.cik == cik,
        FinancialFact.metric == metric,
        FinancialFact.period_class == "annual",
        FinancialFact.derived.is_(False),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.value.is_not(None),
        FinancialFact.unit == "USD",
    )
    if as_of:
        stmt = known_by(stmt, as_of)
    latest: dict[date, FinancialFact] = {}
    for f in db.scalars(stmt):
        cur = latest.get(f.period_end)
        if cur is None or (f.filed_date or date.min, f.accession_number or "") > (
            cur.filed_date or date.min,
            cur.accession_number or "",
        ):
            latest[f.period_end] = f
    return [latest[k] for k in sorted(latest, reverse=True)]


def build_brief(db: Session, company: Company, as_of: date | None = None) -> Brief:
    b = Brief(company=company, as_of=as_of)
    n = b.cite("SEC company profile", company.source_url)
    parts = [f"[{n}] Company: {company.legal_name}"]
    if company.ticker:
        parts.append(f" (ticker {company.ticker}, {company.exchange})")
    parts.append(f"; CIK {company.cik}")
    if company.sic_code:
        parts.append(f"; industry SIC {company.sic_code} {company.sic_description}")
    if company.state_of_incorporation:
        parts.append(f"; state of incorporation {company.state_of_incorporation}")
    if company.fiscal_year_end:
        parts.append(f"; fiscal year ends {company.fiscal_year_end}")
    b.context_lines.append("".join(parts) + ".")
    if as_of:
        b.context_lines.append(f"All figures are as known on {as_of.isoformat()}.")

    for metric, label in METRIC_LABELS.items():
        series = _annual_series(db, company.cik, metric, as_of)
        if not series:
            continue
        cur = series[0]
        prev = series[1] if len(series) > 1 else None
        growth = None
        if prev is not None and prev.value:
            growth = round(float((cur.value - prev.value) / abs(prev.value)) * 100, 1)
        n = b.cite(f"{label}, {cur.form_type} filed {cur.filed_date}", cur.source_url)
        b.metrics.append(
            {
                "metric": metric,
                "label": label,
                "period_end": cur.period_end.isoformat(),
                "value": float(cur.value),
                "display": _money(cur.value),
                "prior_period_end": prev.period_end.isoformat() if prev else None,
                "prior_value": float(prev.value) if prev else None,
                "prior_display": _money(prev.value) if prev else None,
                "growth_pct": growth,
                "filed_date": cur.filed_date.isoformat() if cur.filed_date else None,
                "accession_number": cur.accession_number,
                "source_url": cur.source_url,
                "citation": n,
                "history": [
                    {"period_end": f.period_end.isoformat(), "value": float(f.value)}
                    for f in series[:5]
                ],
            }
        )
        line = f"[{n}] {label}, fiscal year ended {cur.period_end}: {_money(cur.value)}"
        if prev is not None:
            line += f"; prior year (ended {prev.period_end}) {_money(prev.value)}"
            if growth is not None:
                line += f"; change {growth:+.1f}%"
        b.context_lines.append(line + f". Filed {cur.filed_date} ({cur.form_type}).")

    stmt = select(Filing).where(Filing.cik == company.cik)
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    recent = db.scalars(
        stmt.order_by(Filing.filing_date.desc(), Filing.accession_number.desc()).limit(8)
    ).all()
    for f in recent:
        items = split_items(f.items)
        n = b.cite(f"{f.form_type} filed {f.filing_date}", f.source_url)
        b.filings.append(_filing_card(f, items, n))
        line = f"[{n}] Filing: {f.form_type} filed {f.filing_date}"
        if items:
            line += " covering 8-K items " + "; ".join(
                f"{i} {ITEM_TITLES.get(i, '')}" for i in items
            )
        b.context_lines.append(line + ".")

    since = (as_of or date.today()) - timedelta(days=3 * 365)
    leadership = [
        f
        for f in db.scalars(
            stmt.where(Filing.items.like(f"%{LEADERSHIP_ITEM}%"), Filing.filing_date >= since)
            .order_by(Filing.filing_date.desc())
            .limit(5)
        )
        if LEADERSHIP_ITEM in split_items(f.items)
    ]
    for f in leadership:
        n = b.cite(f"8-K item 5.02 filed {f.filing_date}", f.source_url)
        b.leadership_filings.append(_filing_card(f, split_items(f.items), n))
        b.context_lines.append(
            f"[{n}] Leadership change disclosed: 8-K filed {f.filing_date} under item 5.02 "
            "(departure or appointment of directors or officers). Names are in the filing text, "
            "which is not summarised here."
        )
    return b


def _filing_card(f: Filing, items: list[str], n: int) -> dict:
    return {
        "form_type": f.form_type,
        "filing_date": f.filing_date.isoformat() if f.filing_date else None,
        "accession_number": f.accession_number,
        "items": [{"code": i, "title": ITEM_TITLES.get(i)} for i in items],
        "source_url": f.source_url,
        "citation": n,
    }
