"""Everything known about one company, for a single page (issue #9).

Built from stored data only: identity and SEC metadata, former names, the readable profile's
summary, filing history, key annual figures and the company-year table (marts), recent filings
with their 8-K item titles, filing activity by form, leadership changes read from item 5.02,
risk factor categories from a prospectus, peers by SIC and international listings by LEI. Every
figure and event links to its filing on sec.gov; no source API URLs are returned.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    CompanyAlias,
    Filing,
    FinancialFact,
    ListedInstrument,
    MartCompany,
    MartCompanyPeriod,
    OfficerChange,
)
from app.schemas.companies import CompanyOut
from app.services import (
    auditors,
    documents,
    identity,
    insiders,
    ipo_terms,
    leadership,
    live,
    named_successors,
    periods,
    segments,
    statements,
    successions,
    thirteenf,
    ttm,
)
from app.services import cover as cover_service
from app.services.form8k import ITEM_TITLES, split_items
from app.services.form_names import form_label
from app.services.intel import display_name
from app.services.officer_changes import change_dict
from app.services.sec_client import company_filings_url

YEARS = 10
RECENT_FILINGS = 25
LEADERSHIP_YEARS = 3
PEERS = 6
PEER_RECENT_DAYS = 730  # a peer must have filed an annual report in the last two years
EVENT_DAYS = 730
EVENTS = 30
METRICS = ("revenue", "operating_income", "net_income", "total_assets", "operating_cash_flow")
FORM_GROUPS = {
    "Annual reports": ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"),
    "Quarterly reports": ("10-Q", "10-Q/A"),
    "Current reports (8-K)": ("8-K", "8-K/A", "6-K", "6-K/A"),
    "Proxy statements": ("DEF 14A", "DEFA14A", "DEF 14C", "PRE 14A"),
    "Insider transactions": ("3", "4", "5", "3/A", "4/A", "5/A"),
    "Ownership reports": ("SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A", "13F-HR"),
    "Registrations and prospectuses": ("S-1", "S-1/A", "F-1", "F-1/A", "S-3", "S-8", "424B4",
                                       "424B3", "424B2", "424B5", "FWP"),
}  # fmt: skip


def _no_listed_shares(company: Company) -> dict | None:
    """When a company has no 13F holders because it has no listed securities at all (no ticker
    and no exchange listing: a debt-only filer, an operating partnership, a subsidiary), say so,
    so the empty block is not read as a gap. A listed company we failed to match gets None."""
    import json

    def listed(raw):
        try:
            return [x for x in json.loads(raw or "[]") if x]
        except ValueError:
            return []

    if company.ticker or listed(company.tickers) or listed(company.exchanges):
        return None
    return {"listed": False,
            "note": "No listed common stock, so no Form 13F holders."}  # fmt: skip


def _identity(db: Session, company: Company) -> dict:
    out = CompanyOut.model_validate(company).model_dump(mode="json")
    for hidden in ("match_type", "matched_name", "quality_status", "ingestion_status"):
        out.pop(hidden, None)
    out["display_name"] = display_name(company.legal_name, company.ticker,
                                      company.registrant_name)  # fmt: skip
    mart = db.get(MartCompany, company.cik)
    out["reporting_currency"] = mart.reporting_currency if mart else None  # D-04
    # D-01: whether the company still files its own periodic reports (10-K, 10-Q, 20-F, 40-F)
    # within 18 months; the page says "No periodic report since {date}" when it does not
    out["periodic_active"] = bool(mart.periodic_active) if mart else None
    out["last_periodic_report"] = ({"form": mart.last_periodic_form,
                                    "filed_date": mart.last_periodic_date.isoformat()}
                                   if mart and mart.last_periodic_date else None)  # fmt: skip
    from app.services.ticker_history import legal_name_as_filed

    out["legal_name_as_filed"] = legal_name_as_filed(company)  # K-06
    from app.services.ticker_history import incorporation

    out["incorporation"] = incorporation(company)  # code, source, filing
    fye = company.fiscal_year_end
    if fye and fye[:2].isdigit() and 1 <= int(fye[:2]) <= 12:
        out["fiscal_year_end_month"] = date(2000, int(fye[:2]), 1).strftime("%B")
    out["former_names"] = [
        {
            "name": a.alias,
            "from": a.valid_from.isoformat() if a.valid_from else None,
            "to": a.valid_to.isoformat() if a.valid_to else None,
        }
        for a in db.scalars(
            select(CompanyAlias)
            .where(CompanyAlias.cik == company.cik, CompanyAlias.kind == "former")
            .order_by(CompanyAlias.valid_to.desc().nulls_last())
        )
    ]
    out["predecessors"] = [successions.as_dict(db, p, "predecessor")
                           for p in successions.predecessors(db, company.cik)]  # fmt: skip
    nxt = successions.successor(db, company.cik)
    out["successor"] = successions.as_dict(db, nxt, "successor") if nxt else None
    # D-01b: the company a stopped registrant's own filings name as its successor (display only;
    # K-05's reviewed successor above takes precedence)
    stopped = nxt is None and out.get("periodic_active") is False
    out["succeeded_by"] = named_successors.succeeded_by(db, company.cik) if stopped else None
    out["former_tickers"] = [
        {"ticker": a.alias, "to": a.valid_to.isoformat() if a.valid_to else None}
        for a in db.scalars(
            select(CompanyAlias)
            .where(CompanyAlias.cik == company.cik, CompanyAlias.kind == "former_ticker")
            .order_by(CompanyAlias.valid_to.desc().nulls_last())
        )
    ]
    return out


def _history(mart: MartCompany | None) -> dict | None:
    if mart is None:
        return None
    return {
        "first_filing_date": mart.first_filing_date,
        "latest_filing_date": mart.latest_filing_date,
        "filings_last_12_months": mart.filings_last_12_months,
        "active": mart.active,
        "first_registration": {"form": mart.first_registration_form,
                               "filing_date": mart.first_registration_date}
        if mart.first_registration_date else None,
        "ipo_prospectus": {"filing_date": mart.ipo_prospectus_date,
                           "source_url": mart.ipo_prospectus_url}
        if mart.ipo_prospectus_date else None,
        "latest_annual_report": {"form": mart.latest_annual_report_form,
                                 "filing_date": mart.latest_annual_report_date}
        if mart.latest_annual_report_date else None,
    }  # fmt: skip


def _key_figures(mart: MartCompany | None, fye: str | None) -> list[dict]:
    latest = json.loads(mart.latest_annual) if mart and mart.latest_annual else {}
    history = json.loads(mart.revenue_history) if mart and mart.revenue_history else []
    out = []
    for metric in METRICS:
        v = latest.get(metric)
        if not v:
            continue
        end = date.fromisoformat(v["period_end"])
        item = {
            "metric": metric,
            "value": v["value"],
            "unit": v.get("unit", "USD"),
            "currency": v.get("unit", "USD"),  # D-04: the company's reporting currency
            "period_end": v["period_end"],
            "fiscal_label": periods.label(end, "annual", fye),
            "form_type": v["form_type"],
            "filed_date": v["filed_date"],
            "source_url": v.get("url"),
        }
        if metric == "revenue" and len(history) > 1 and history[1]["value"]:
            item["change_pct"] = round(
                (history[0]["value"] - history[1]["value"]) / abs(history[1]["value"]) * 100, 1
            )
        out.append(item)
    return out


def _years(db: Session, cik: str, fye: str | None) -> list[dict]:
    rows = list(db.scalars(
        select(MartCompanyPeriod)
        .where(MartCompanyPeriod.cik == cik)
        .order_by(MartCompanyPeriod.fiscal_year.desc())
        .limit(YEARS)
    ))  # fmt: skip
    have = {r.period_end for r in rows}
    for p in successions.predecessors(db, cik):  # K-05: the years before the new registrant
        for r in db.scalars(select(MartCompanyPeriod).where(MartCompanyPeriod.cik
                                                            == p.predecessor_cik)):  # fmt: skip
            if r.period_end not in have and all(abs((r.period_end - e).days) > 45 for e in have):
                rows.append(r)
                have.add(r.period_end)
    rows = sorted(rows, key=lambda r: r.period_end, reverse=True)[:YEARS]
    out = []
    for r in reversed(rows):
        values = {m: float(getattr(r, m)) if getattr(r, m) is not None else None for m in METRICS}
        rev, op = values["revenue"], values["operating_income"]
        out.append(
            {
                "fiscal_year": r.fiscal_year,
                "fiscal_label": periods.label(r.period_end, "annual", fye),
                "period_end": r.period_end,
                **values,
                "operating_margin_pct": round(100 * op / rev, 1)
                if rev and op is not None
                else None,
                "sources": json.loads(r.sources) if r.sources else {},
                **statements.registrant(r, cik),
                "currency": r.currency,
            }
        )
    return out


def _filings(db: Session, cik: str, as_of: date | None = None) -> list[dict]:
    stmt = select(Filing).where(Filing.cik == cik)
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    rows = db.scalars(
        stmt.order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc()).limit(
            RECENT_FILINGS
        )
    ).all()
    return [
        {
            "form_type": f.form_type,
            "form_label": form_label(f.form_type),
            "filing_date": f.filing_date,
            "report_date": f.report_date,
            "accession_number": f.accession_number,
            "items": [{"code": i, "title": ITEM_TITLES.get(i)} for i in split_items(f.items)],
            "source_url": f.source_url,
        }
        for f in rows
    ]


def _activity(db: Session, cik: str, today: date) -> list[dict]:
    since = today - timedelta(days=365)
    rows = db.execute(
        select(
            Filing.form_type,
            func.count(Filing.id),
            func.sum(case((Filing.filing_date >= since, 1), else_=0)),
        )
        .where(Filing.cik == cik, Filing.filing_date <= today)
        .group_by(Filing.form_type)
    ).all()
    counts = {form: (int(total), int(recent or 0)) for form, total, recent in rows}
    out, used = [], set()
    for group, forms in FORM_GROUPS.items():
        total = sum(counts.get(f, (0, 0))[0] for f in forms)
        recent = sum(counts.get(f, (0, 0))[1] for f in forms)
        used.update(forms)
        if total:
            out.append({"group": group, "total": total, "last_12_months": recent})
    other = [(t, r) for f, (t, r) in counts.items() if f not in used]
    if other:
        out.append({"group": "Other filings", "total": sum(t for t, _ in other),
                    "last_12_months": sum(r for _, r in other)})  # fmt: skip
    return out


def _leadership(db: Session, cik: str, today: date) -> dict:
    since = today - timedelta(days=365 * LEADERSHIP_YEARS)
    changes = db.scalars(
        select(OfficerChange)
        .where(
            OfficerChange.cik == cik,
            OfficerChange.filing_date >= since,
            OfficerChange.filing_date <= today,
        )
        .order_by(OfficerChange.filing_date.desc(), OfficerChange.seq)
        .limit(20)
    ).all()
    filings_502 = db.scalar(
        select(func.count(Filing.id)).where(
            Filing.cik == cik,
            Filing.items.like("%5.02%"),
            Filing.filing_date >= since,
            Filing.filing_date <= today,
        )
    )
    return {
        "since": since,
        "item_502_filings": int(filings_502 or 0),
        "changes": [
            {"filing_date": c.filing_date, "accession_number": c.accession_number,
             "source_url": c.source_url, **{k: v for k, v in change_dict(c).items()
                                           if k != "context"}}
            for c in changes
        ],
    }  # fmt: skip


def _people(db: Session, cik: str, today: date) -> dict:
    """U-03: leadership by person and the current CEO, CFO and chair (with K-02)."""
    owners = insiders.roles(db, cik, today)
    leadership.apply_to_roles(db, cik, owners, today)
    return leadership.overview(db, cik, owners, today)


PEER_MIN = 4  # widen the industry only until this many peers fall in the revenue band
PEER_BAND = 10.0  # a peer's revenue is within 1/10 to 10 times the company's
_PEER_GROUP_WORDS = {"GROUP", "HOLDINGS", "HOLDING", "INC", "CORP", "CORPORATION", "CO", "COMPANY",
                     "LTD", "LIMITED", "PLC", "AG", "SA", "SE", "NV", "ASA", "AB", "LLC", "LP",
                     "THE", "OF", "&", "AND"}  # fmt: skip


def _group_key(name: str) -> str:
    """'UBS Group AG' and 'UBS AG' -> 'UBS': one registrant per group in a peer list."""
    words = [w for w in re.sub(r"[^A-Za-z0-9& ]", " ", (name or "").upper()).split()
             if w not in _PEER_GROUP_WORDS]  # fmt: skip
    return " ".join(words[:2])


def _accounting(db: Session, ciks: list[str]) -> dict[str, str]:
    """us-gaap or ifrs per company, from the taxonomy of its latest reported revenue."""
    if not ciks:
        return {}
    rows = db.execute(
        select(FinancialFact.cik, FinancialFact.source_taxonomy)
        .where(FinancialFact.cik.in_(ciks), FinancialFact.metric == "revenue",
               FinancialFact.derived.is_(False))
        .order_by(FinancialFact.cik, FinancialFact.period_end.desc())
        .distinct(FinancialFact.cik)
    ).all() if db.bind.dialect.name == "postgresql" else [
        (c, db.scalar(select(FinancialFact.source_taxonomy).where(
            FinancialFact.cik == c, FinancialFact.metric == "revenue",
            FinancialFact.derived.is_(False)).order_by(FinancialFact.period_end.desc()).limit(1)))
        for c in ciks]  # fmt: skip
    return {c: ("ifrs" if (t or "").startswith("ifrs") else "us-gaap") for c, t in rows if t}


def _peers(db: Session, company: Company, today: date) -> dict | None:
    """Peers (U-02, X-19): the same industry (4-digit SIC, widened to 3 then 2 digits only to fill
    the band), the same accounting basis, an annual report in the last two years, and revenue
    within 0.1x to 10x of the company's latest annual revenue in the same currency, nearest
    first. One registrant per group; a predecessor gives way to its successor (K-05), and a
    successor without revenue of its own is sized by its predecessor's."""
    from app.core.config import get_settings
    from app.services import successions
    from app.services.public import showcase_ciks

    code = company.sic_code
    if not code or len(code) < 3:
        return None
    me = db.get(MartCompany, company.cik)
    sized_by = None
    if not (me and me.latest_revenue):
        for r in successions.predecessors(db, company.cik):
            pm = db.get(MartCompany, r.predecessor_cik)
            if pm and pm.latest_revenue:
                me, sized_by = pm, r.predecessor_cik
                break
    mine = float(me.latest_revenue) if me and me.latest_revenue else None
    cur = me.reporting_currency if me else None
    own_basis = _accounting(db, [me.cik if me else company.cik]).get(me.cik if me else company.cik)
    recent = today - timedelta(days=PEER_RECENT_DAYS)
    exclude = {company.cik} | {r.predecessor_cik for r in successions.predecessors(db, company.cik)}

    def in_band(m: MartCompany) -> bool:
        if not mine or mine <= 0 or m.reporting_currency != cur:
            return False
        return 1 / PEER_BAND <= float(m.latest_revenue) / mine <= PEER_BAND

    rows, basis_of, width = [], {}, 4
    for width in (4, 3, 2):
        if len(code) < width:
            continue
        rows = db.execute(
            select(MartCompany, Company)
            .join(Company, Company.cik == MartCompany.cik)
            .where(
                func.substr(Company.sic_code, 1, width) == code[:width],
                MartCompany.cik.not_in(exclude),
                MartCompany.latest_revenue.is_not(None),
                MartCompany.latest_revenue > 0,
                MartCompany.latest_annual_report_date >= recent,
                MartCompany.latest_revenue_period_end >= recent - timedelta(days=365),
            )
        ).all()
        basis_of = _accounting(db, [m.cik for m, _ in rows])
        if own_basis:
            rows = [(m, c) for m, c in rows if basis_of.get(m.cik, own_basis) == own_basis]
        if not mine or sum(1 for m, _ in rows if in_band(m)) >= PEER_MIN:
            break
    if not rows:
        return None

    def distance(m: MartCompany) -> float:
        if not mine or mine <= 0:
            return -float(m.latest_revenue)  # no revenue of our own: largest first
        return abs(math.log(float(m.latest_revenue) / mine))

    # D-04: sizes compare only within one currency (never converted); when fewer than four peers
    # share it, same-industry companies in other currencies fill in, unranked
    if mine:
        same = sorted((r for r in rows if in_band(r[0])), key=lambda r: distance(r[0]))
    else:
        same = sorted((r for r in rows if r[0].reporting_currency == cur),
                      key=lambda r: distance(r[0]))  # fmt: skip
    others = sorted((r for r in rows if r[0].reporting_currency != cur),
                    key=lambda r: r[0].legal_name)  # fmt: skip
    groups = {_group_key(company.registrant_name or company.legal_name)}
    chosen = []
    for r, ranked in [(r, True) for r in same] + [(r, False) for r in others]:
        if len(chosen) >= PEERS or (not ranked and len(chosen) >= PEER_MIN):
            break
        m, c = r
        succ = successions.successor(db, m.cik)
        shown = None
        if succ:
            shown = db.scalar(select(Company).where(Company.cik == succ.successor_cik))
        key = _group_key((shown or c).registrant_name or (shown or c).legal_name)
        if key in groups or (shown is not None and shown.cik in exclude):
            continue
        groups.add(key)
        chosen.append((m, c, shown, ranked))
    showcase = set(showcase_ciks(db, get_settings())[0])

    def peer(m: MartCompany, c: Company, shown: Company | None, ranked: bool) -> dict:
        who = shown or c
        rev = (json.loads(m.latest_annual or "{}") or {}).get("revenue") or {}
        out = {
            "cik": who.cik,
            "name": display_name(who.legal_name, who.ticker, who.registrant_name),
            "ticker": who.ticker, "latest_revenue": float(m.latest_revenue),
            "currency": m.reporting_currency, "ranked": ranked,
            "accounting": basis_of.get(m.cik),
            "period_end": m.latest_revenue_period_end,
            "fiscal_label": periods.label(m.latest_revenue_period_end, "annual",
                                          periods.convention(c))
            if m.latest_revenue_period_end else None,
            "accession_number": rev.get("accession"), "form_type": rev.get("form_type"),
            "filed_date": rev.get("filed_date"), "source_url": rev.get("url"),
            "filings_url": company_filings_url(who.cik),
            "is_public_page": who.cik in showcase,
        }  # fmt: skip
        if shown is not None:
            out["revenue_reported_by"] = {
                "cik": c.cik, "name": display_name(c.legal_name, c.ticker, c.registrant_name),
                "note": "revenue as last reported by the predecessor registrant"}  # fmt: skip
        if not ranked:
            out["note"] = "different currency, not ranked by size"
        return out

    level = {4: "the same industry", 3: "a related industry", 2: "the same industry group"}[width]
    sic = f"SIC {code[:width]}" + (f", {company.sic_description}" if width == 4 and
                                    company.sic_description else "")  # fmt: skip
    own = {"us-gaap": "US GAAP", "ifrs": "IFRS"}.get(own_basis or "", "")
    if mine:
        basis = (f"Companies in {level} ({sic}) that report under {own or 'the same basis'}, "
                 "filed an annual report in the last two years and had revenue between a tenth "
                 "and ten times this company's latest annual revenue"
                 + (" (as last reported by its predecessor)" if sized_by else "")
                 + ", nearest in size first; one registrant per group.")  # fmt: skip
    else:
        basis = (f"Companies in {level} ({sic}) that report under {own or 'the same basis'} and "
                 "filed an annual report in the last two years, largest first (this company "
                 "has no annual revenue to compare); one registrant per group.")  # fmt: skip
    return {
        "basis": basis,
        "basis_width": width,
        "sic": code[:width],
        "accounting": own_basis,
        "currency": cur,
        "revenue_band": [round(mine / PEER_BAND, 2), round(mine * PEER_BAND, 2)] if mine else None,
        "sized_by_predecessor": sized_by,
        "companies": [peer(*x) for x in chosen],
    }


def _figures_as_of(db: Session, company: Company, as_of: date) -> tuple[list[dict], list[dict]]:
    """key_figures and years as known on as_of, from the reported facts (not the marts)."""
    cells, units, ends = statements.annual_cells(db, company, as_of, METRICS)
    labels = sorted(ends, key=lambda lab: ends[lab])[-YEARS:]
    key_figures = []
    for metric in METRICS:
        per = cells.get(metric, {})
        if not per:
            continue
        lab = max(per, key=lambda x: per[x].period_end)
        f = per[lab]
        item = {"metric": metric, "value": float(f.value), "unit": f.unit, "currency": f.unit,
                "period_end": f.period_end, "fiscal_label": lab, "form_type": f.form_type,
                "filed_date": f.filed_date, "source_url": f.source_url}  # fmt: skip
        prev = sorted(per.values(), key=lambda x: x.period_end)
        if metric == "revenue" and len(prev) > 1 and prev[-2].value:
            item["change_pct"] = round(
                float((prev[-1].value - prev[-2].value) / abs(prev[-2].value)) * 100, 1
            )
        key_figures.append(item)
    years = []
    for lab in labels:
        values = {m: float(cells[m][lab].value) if lab in cells.get(m, {}) else None
                  for m in METRICS}  # fmt: skip
        rev, op = values["revenue"], values["operating_income"]
        years.append({
            "fiscal_year": int(lab[2:6]) if lab[2:6].isdigit() else None,
            "fiscal_label": lab, "period_end": ends[lab], **values,
            "operating_margin_pct": round(100 * op / rev, 1) if rev and op is not None else None,
            "sources": {m: cells[m][lab].source_url for m in METRICS if lab in cells.get(m, {})},
            "currency": units.get("revenue"),
        })  # fmt: skip
    return key_figures, years


def _listings(db: Session, company: Company) -> list[dict]:
    if not company.lei:
        return []
    return [
        {"isin": r.isin, "mic": r.mic, "status": r.status, "first_trade_date": r.first_trade_date,
         "currency": r.currency}
        for r in db.scalars(
            select(ListedInstrument).where(ListedInstrument.issuer_lei == company.lei)
        )
    ]  # fmt: skip


POINT_IN_TIME = ("statements", "key_figures", "years", "cover", "filings", "filing_activity",
                 "insider_activity", "leadership", "events", "ownership",
                 "auditor", "segments")  # fmt: skip
CURRENT = ("summary", "history", "risk_factors", "peers", "listings")


def first_filing_date(db: Session, cik: str) -> date | None:
    """The first filing of the company, its predecessor registrants' included (K-05)."""
    ciks = [cik] + [p.predecessor_cik for p in successions.predecessors(db, cik)]
    return db.scalar(select(func.min(Filing.filing_date)).where(Filing.cik.in_(ciks)))


def _card_fields(db: Session, cik: str, key_figures: list[dict], years: list[dict]) -> None:
    """X-01a: each figure carries what the provenance card shows (accession, tag, mapping
    version, quality) beside its filing link, matched to the stored fact by metric, period end
    and filing. Years get them in `provenance` ({metric: {...}}); `sources` keeps its URLs."""
    urls = {kf.get("source_url") for kf in key_figures} | {
        u for y in years for u in (y.get("sources") or {}).values()
    }
    urls.discard(None)
    if not urls:
        return
    rows = db.execute(
        select(FinancialFact.metric, FinancialFact.period_end, FinancialFact.source_url,
               FinancialFact.accession_number, FinancialFact.source_tag,
               FinancialFact.mapping_version, FinancialFact.quality_status)
        .where(FinancialFact.cik == cik, FinancialFact.metric.in_(METRICS),
               FinancialFact.derived.is_(False), FinancialFact.source_url.in_(urls))
    ).all()  # fmt: skip
    card = {(m, str(end), url): {"accession_number": acc, "source_tag": tag,
                                 "mapping_version": mv, "quality_status": qs}
            for m, end, url, acc, tag, mv, qs in rows}  # fmt: skip
    for kf in key_figures:
        kf.update(card.get((kf["metric"], str(kf["period_end"]), kf.get("source_url")), {}))
    for y in years:
        y["provenance"] = {
            m: card[(m, str(y["period_end"]), url)]
            for m, url in (y.get("sources") or {}).items()
            if (m, str(y["period_end"]), url) in card
        }


def build(
    db: Session, cik: str, today: date | None = None, as_of: date | None = None
) -> dict | None:
    today = today or date.today()
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        return None
    anchor = as_of or today
    mart = db.get(MartCompany, cik)
    profile = documents.build_profile(db, cik, today=today)
    risk = documents.latest_risk(db, cik)
    if as_of:
        key_figures, years = _figures_as_of(db, company, as_of)
    else:
        key_figures = _key_figures(mart, periods.convention(company))
        years = _years(db, cik, periods.convention(company))
    _card_fields(db, cik, key_figures, years)
    trailing = ttm.compute(db, company, list(METRICS), as_of=as_of, today=today)
    for kf in key_figures:
        if kf["metric"] in trailing:
            kf["ttm"] = trailing[kf["metric"]]
    return {
        "company": _identity(db, company),
        "as_of": as_of.isoformat() if as_of else None,
        "as_of_scope": {"point_in_time": list(POINT_IN_TIME), "current": list(CURRENT)},
        "summary": {"text": profile.summary, "citations": profile.citations} if profile else None,
        "history": _history(mart),
        "key_figures": key_figures,
        "years": years,
        "statements": statements.build(db, company, as_of),
        "cover": cover_service.cover(db, company, as_of),
        "filings": _filings(db, cik, as_of),
        "filing_activity": _activity(db, cik, anchor),
        "leadership": {**_leadership(db, cik, anchor), **_people(db, cik, anchor)},
        "events": live.event_rows(
            db, anchor - timedelta(days=EVENT_DAYS), EVENTS, until=anchor, cik=cik
        ),
        "ipo_terms": ipo_terms.terms_by_cik(db, [cik]).get(cik),
        "insider_activity": live.insider_rows(
            db, anchor - timedelta(days=EVENT_DAYS), EVENTS, until=anchor, cik=cik
        ),
        "ownership": thirteenf.for_company(db, company, as_of, today=today)
        or _no_listed_shares(company),
        "auditor": auditors.for_company(db, cik, as_of),
        "segments": segments.for_company(db, cik, as_of),
        "risk_factors": risk,
        "peers": _peers(db, company, today),
        "listings": _listings(db, company),
        "identity": identity.for_company(db, cik),
        "notes": [
            "Figures are as reported in the company's annual reports; each links to its filing "
            "on sec.gov. Missing values mean no mappable figure was filed, not that there is none.",
            "Ratios are derived here from two reported figures of the same fiscal year and list "
            "their inputs.",
            "Events say what a filing is, from its form and declared 8-K items: information, "
            "not signals.",
            "Ownership is from Forms 13F filed by institutional investment managers for the "
            "latest complete quarter; each holder links to its filing.",
            "Leadership changes are read from 8-K item 5.02 by a language model and checked "
            "against the filing text; unverified ones are marked.",
            "Data from SEC EDGAR. Independent service, not affiliated with the SEC. Not "
            "investment advice.",
        ],
    }
