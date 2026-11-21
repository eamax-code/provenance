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
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    CompanyAlias,
    Filing,
    ListedInstrument,
    MartCompany,
    MartCompanyPeriod,
    OfficerChange,
)
from app.schemas.companies import CompanyOut
from app.services import cover as cover_service
from app.services import documents, ipo_terms, live, periods, statements
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


def _identity(db: Session, company: Company) -> dict:
    out = CompanyOut.model_validate(company).model_dump(mode="json")
    for hidden in ("match_type", "matched_name", "quality_status", "ingestion_status"):
        out.pop(hidden, None)
    out["display_name"] = display_name(company.legal_name)
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
            .where(CompanyAlias.cik == company.cik)
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
    rows = db.scalars(
        select(MartCompanyPeriod)
        .where(MartCompanyPeriod.cik == cik)
        .order_by(MartCompanyPeriod.fiscal_year.desc())
        .limit(YEARS)
    ).all()
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


def _peers(db: Session, company: Company, today: date) -> dict | None:
    """Same 4-digit SIC (3-digit when fewer than 4 peers), companies that filed an annual report
    in the last two years, ranked by closeness to this company's latest annual revenue (U-02)."""
    code = company.sic_code
    if not code or len(code) < 3:
        return None
    me = db.get(MartCompany, company.cik)
    mine = float(me.latest_revenue) if me and me.latest_revenue else None
    recent = today - timedelta(days=PEER_RECENT_DAYS)
    for width in (4, 3):
        prefix = code[:width]
        rows = db.execute(
            select(MartCompany, Company.fiscal_year_end)
            .join(Company, Company.cik == MartCompany.cik)
            .where(
                func.substr(Company.sic_code, 1, width) == prefix,
                MartCompany.cik != company.cik,
                MartCompany.latest_revenue.is_not(None),
                MartCompany.latest_revenue > 0,
                MartCompany.latest_annual_report_date >= recent,
                MartCompany.latest_revenue_period_end >= recent - timedelta(days=365),
            )
        ).all()
        if len(rows) >= 4 or width == 3:
            break
    if not rows:
        return None

    def distance(m: MartCompany) -> float:
        if not mine or mine <= 0:
            return -float(m.latest_revenue)  # no revenue of our own: largest first
        return abs(math.log(float(m.latest_revenue) / mine))

    rows.sort(key=lambda r: distance(r[0]))
    return {
        "basis": f"SIC {prefix}" + (f" ({company.sic_description})" if width == 4 else ""),
        "basis_width": width,
        "companies": [
            {
                "cik": m.cik,
                "name": display_name(m.legal_name),
                "ticker": m.ticker,
                "latest_revenue": float(m.latest_revenue),
                "period_end": m.latest_revenue_period_end,
                "fiscal_label": periods.label(m.latest_revenue_period_end, "annual", fye)
                if m.latest_revenue_period_end
                else None,
                "filings_url": company_filings_url(m.cik),
            }
            for m, fye in rows[:PEERS]
        ],
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
        item = {"metric": metric, "value": float(f.value), "unit": f.unit,
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
                 "insider_activity", "leadership", "events")  # fmt: skip
CURRENT = ("summary", "history", "risk_factors", "peers", "listings")


def first_filing_date(db: Session, cik: str) -> date | None:
    return db.scalar(select(func.min(Filing.filing_date)).where(Filing.cik == cik))


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
        key_figures = _key_figures(mart, company.fiscal_year_end)
        years = _years(db, cik, company.fiscal_year_end)
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
        "leadership": _leadership(db, cik, anchor),
        "events": live.event_rows(
            db, anchor - timedelta(days=EVENT_DAYS), EVENTS, until=anchor, cik=cik
        ),
        "ipo_terms": ipo_terms.terms_by_cik(db, [cik]).get(cik),
        "insider_activity": live.insider_rows(
            db, anchor - timedelta(days=EVENT_DAYS), EVENTS, until=anchor, cik=cik
        ),
        "risk_factors": risk,
        "peers": _peers(db, company, today),
        "listings": _listings(db, company),
        "notes": [
            "Figures are as reported in the company's annual reports; each links to its filing "
            "on sec.gov. Missing values mean no mappable figure was filed, not that there is none.",
            "Ratios are derived here from two reported figures of the same fiscal year and list "
            "their inputs.",
            "Events say what a filing is, from its form and declared 8-K items: information, "
            "not signals.",
            "Leadership changes are read from 8-K item 5.02 by a language model and checked "
            "against the filing text; unverified ones are marked.",
            "Data from SEC EDGAR. Independent service, not affiliated with the SEC. Not "
            "investment advice.",
        ],
    }
