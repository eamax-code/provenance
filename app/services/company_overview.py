"""Everything known about one company, for a single page (issue #9).

Built from stored data only: identity and SEC metadata, former names, the readable profile's
summary, filing history, key annual figures and the company-year table (marts), recent filings
with their 8-K item titles, filing activity by form, leadership changes read from item 5.02,
risk factor categories from a prospectus, peers by SIC and international listings by LEI. Every
figure and event links to its filing on sec.gov; no source API URLs are returned.
"""

from __future__ import annotations

import json
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
from app.services import documents, periods
from app.services.form8k import ITEM_TITLES, split_items
from app.services.intel import display_name
from app.services.officer_changes import change_dict
from app.services.sec_client import company_filings_url

YEARS = 10
RECENT_FILINGS = 25
LEADERSHIP_YEARS = 3
PEERS = 8
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


def _filings(db: Session, cik: str) -> list[dict]:
    rows = db.scalars(
        select(Filing)
        .where(Filing.cik == cik)
        .order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
        .limit(RECENT_FILINGS)
    ).all()
    return [
        {
            "form_type": f.form_type,
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
        .where(Filing.cik == cik)
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
        .where(OfficerChange.cik == cik, OfficerChange.filing_date >= since)
        .order_by(OfficerChange.filing_date.desc(), OfficerChange.seq)
        .limit(20)
    ).all()
    filings_502 = db.scalar(
        select(func.count(Filing.id)).where(
            Filing.cik == cik, Filing.items.like("%5.02%"), Filing.filing_date >= since
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


def _peers(db: Session, company: Company) -> dict | None:
    code = company.sic_code
    if not code:
        return None
    for width in (4, 2):
        prefix = code[:width]
        rows = (
            db.execute(
                select(MartCompany)
                .join(Company, Company.cik == MartCompany.cik)
                .where(
                    func.substr(Company.sic_code, 1, width) == prefix,
                    MartCompany.cik != company.cik,
                    MartCompany.latest_revenue.is_not(None),
                    MartCompany.active.is_(True),
                )
                .order_by(MartCompany.latest_revenue.desc())
                .limit(PEERS)
            )
            .scalars()
            .all()
        )
        if len(rows) >= 3 or width == 2:
            break
    if not rows:
        return None
    return {
        "basis": f"SIC {prefix}" + (f" ({company.sic_description})" if width == 4 else ""),
        "companies": [
            {
                "cik": m.cik,
                "name": display_name(m.legal_name),
                "ticker": m.ticker,
                "latest_revenue": float(m.latest_revenue),
                "period_end": m.latest_revenue_period_end,
                "filings_url": company_filings_url(m.cik),
            }
            for m in rows
        ],
    }


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


def build(db: Session, cik: str, today: date | None = None) -> dict | None:
    today = today or date.today()
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        return None
    mart = db.get(MartCompany, cik)
    profile = documents.build_profile(db, cik, today=today)
    risk = documents.latest_risk(db, cik)
    return {
        "company": _identity(db, company),
        "summary": {"text": profile.summary, "citations": profile.citations} if profile else None,
        "history": _history(mart),
        "key_figures": _key_figures(mart, company.fiscal_year_end),
        "years": _years(db, cik, company.fiscal_year_end),
        "filings": _filings(db, cik),
        "filing_activity": _activity(db, cik, today),
        "leadership": _leadership(db, cik, today),
        "risk_factors": risk,
        "peers": _peers(db, company),
        "listings": _listings(db, company),
        "notes": [
            "Figures are as reported in the company's annual reports; each links to its filing "
            "on sec.gov. Missing values mean no mappable figure was filed, not that there is none.",
            "Leadership changes are read from 8-K item 5.02 by a language model and checked "
            "against the filing text; unverified ones are marked.",
            "Data from SEC EDGAR. Independent service, not affiliated with the SEC. Not "
            "investment advice.",
        ],
    }
