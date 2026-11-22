"""A server-rendered head for public company pages (search and link previews): title,
description, canonical link, Open Graph tags and JSON-LD, from stored data only. Companies
outside the public pages get a generic head marked noindex."""

from __future__ import annotations

import html
import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, MartCompany
from app.services import identity, periods, statements
from app.services.intel import display_name
from app.services.public import cached, showcase_ciks
from app.services.sec_client import company_filings_url

DESC_MAX = 160


def _money(v: float, currency: str | None = "USD") -> str:
    """$1.2 billion in USD; "EUR 36.8 billion" in another reporting currency (D-04)."""
    sym = "$" if currency in (None, "USD") else f"{currency} "
    for div, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(v) >= div:
            return f"{sym}{v / div:,.1f} {word}"
    return f"{sym}{v:,.0f}"


def head_for(db: Session, settings, cik: str, origin: str) -> dict:
    def build():
        allowed, _ = showcase_ciks(db, settings)
        company = db.scalar(select(Company).where(Company.cik == cik))
        if company is None or cik not in allowed:
            return {"noindex": True}
        name = display_name(company.legal_name)
        ticker = company.ticker
        canonical = f"{origin}/companies/{cik}"
        title = (f"{name} ({ticker}) revenue, financials and SEC filings · Provenance" if ticker
                 else f"{name} financials and SEC filings · Provenance")  # fmt: skip
        mart = db.get(MartCompany, cik)
        latest = json.loads(mart.latest_annual) if mart and mart.latest_annual else {}
        history = json.loads(mart.revenue_history) if mart and mart.revenue_history else []
        rev = latest.get("revenue")
        tail = ("Financial statements, 8-K events, leadership and filings, every figure linked "
                "to its SEC filing.")  # fmt: skip
        if rev:
            fy = periods.label(date.fromisoformat(rev["period_end"]), "annual",
                               company.fiscal_year_end)  # fmt: skip
            who = (
                f"{name} ({', '.join(x for x in (ticker, company.exchange) if x)})"
                if ticker
                else name
            )
            change = ""
            if len(history) > 1 and history[1]["value"]:
                pct = (history[0]["value"] - history[1]["value"]) / abs(history[1]["value"]) * 100
                change = f", {'up' if pct >= 0 else 'down'} {abs(pct):.1f}%"
            amount = _money(rev["value"], rev.get("unit"))
            desc = f"{who} reported revenue of {amount} in {fy}{change}. {tail}"
            if len(desc) > DESC_MAX:
                desc = f"{who} reported revenue of {amount} in {fy}. {tail}"
        else:
            desc = (f"{name}: financial statements, 8-K events, leadership and filings from the "
                    "SEC, every figure linked to its filing.")  # fmt: skip
        if len(desc) > DESC_MAX:
            desc = desc[: DESC_MAX - 1].rsplit(" ", 1)[0] + "…"
        st = statements.build(db, company)
        rows = [r["label"] for s in st["sections"] if s["key"] != "ratios" for r in s["rows"]]
        ident = identity.for_company(db, cik)
        ids = [{"@type": "PropertyValue", "propertyID": "SEC CIK", "value": cik}]
        if ident:
            ids.append({"@type": "PropertyValue", "propertyID": "LEI", "value": ident["lei"]})
        org = {"@type": "Corporation", "@id": f"{canonical}#org", "name": name,
               "legalName": company.legal_name, "identifier": ids}  # fmt: skip
        if ticker and company.exchange:
            org["tickerSymbol"] = f"{company.exchange.upper()}:{ticker}"
        addr = _address(company.business_address)
        if addr:
            org["address"] = addr
        fys = st["fiscal_years"]
        dataset = {
            "@type": "Dataset", "name": f"{name} financial figures from SEC filings",
            "description": f"Annual figures as reported in {name}'s annual reports, each linked "
                           "to the filing it came from.",
            "about": {"@id": f"{canonical}#org"},
            "creator": {"@type": "Organization", "name": "Provenance", "url": f"{origin}/"},
            "isBasedOn": company_filings_url(cik), "variableMeasured": rows, "url": canonical,
            "distribution": {"@type": "DataDownload", "encodingFormat": "application/json",
                             "contentUrl": f"{origin}/v1/public/companies/{cik}/overview"},
        }  # fmt: skip
        if fys:
            dataset["temporalCoverage"] = f"{fys[0][2:6]}/{fys[-1][2:6]}"
        return {"noindex": False, "title": title, "description": desc, "canonical": canonical,
                "og_title": title.removesuffix(" · Provenance"),
                "jsonld": {"@context": "https://schema.org", "@graph": [org, dataset]}}  # fmt: skip

    return cached(f"seo:{cik}:{origin}", build)


def _address(raw) -> dict | None:
    try:
        a = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(a, dict) or not a.get("city"):
        return None
    out = {"@type": "PostalAddress", "streetAddress": " ".join(
        x for x in (a.get("street1"), a.get("street2")) if x) or None,
        "addressLocality": a.get("city"), "addressRegion": a.get("stateOrCountry"),
        "postalCode": a.get("zipCode"), "addressCountry": a.get("country")}  # fmt: skip
    return {k: v for k, v in out.items() if v}


def render(page: str, head: dict) -> str:
    """The page with its head filled in for this company (or marked noindex)."""
    if head.get("noindex"):
        return page.replace("</head>", '<meta name="robots" content="noindex">\n</head>', 1)
    e = html.escape
    page = re.sub(r"<title>.*?</title>", f"<title>{e(head['title'])}</title>", page, count=1,
                  flags=re.S)  # fmt: skip
    page = re.sub(
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{e(head["description"])}">',
        page,
        count=1,
    )
    page = re.sub(
        r'<meta property="og:title" content="[^"]*">',
        f'<meta property="og:title" content="{e(head["og_title"])}">',
        page,
        count=1,
    )
    page = re.sub(r'<meta property="og:description" content="[^"]*">',
                  f'<meta property="og:description" content="{e(head["description"])}">', page,
                  count=1)  # fmt: skip
    page = re.sub(r'<link rel="canonical" href="[^"]*">\n?', "", page)
    ld = json.dumps(head["jsonld"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    extra = (f'<link rel="canonical" href="{e(head["canonical"])}">\n'
             f'<meta property="og:url" content="{e(head["canonical"])}">\n'
             f'<script type="application/ld+json">{ld}</script>\n')  # fmt: skip
    return page.replace("</head>", extra + "</head>", 1)
