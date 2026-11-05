"""Readable company profiles (issue #3, step 3).

A profile is a short Markdown document per company built from the marts, the filings list and
the officer changes read from 8-K item 5.02. Every figure and event links to the filing it came
from. The chat answers "summarise X" from it without the model, `GET /v1/companies/{cik}/profile`
returns it, and `company_documents` stores it for search across companies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyDocument, Filing, MartCompany, OfficerChange
from app.services import periods
from app.services.form8k import ITEM_TITLES, split_items

PROFILE_METRICS = (
    ("revenue", "Revenue"),
    ("operating_income", "Operating income"),
    ("net_income", "Net income"),
    ("total_assets", "Total assets"),
    ("operating_cash_flow", "Operating cash flow"),
)
RECENT_FILINGS = 5
RECENT_CHANGES = 5
LEADERSHIP_YEARS = 2
MONTHS = (
    "January February March April May June July August September October November December"
).split()


@dataclass
class Profile:
    cik: str
    name: str
    markdown: str
    summary: str  # a few cited sentences, numbers in brackets refer to `citations`
    citations: list[dict] = field(default_factory=list)


def _money(v: float | None) -> str:
    if v is None:
        return "not reported"
    a, s = abs(v), "-$" if v < 0 else "$"
    if a >= 1e9:
        return f"{s}{a / 1e9:,.1f} billion"
    if a >= 1e6:
        return f"{s}{a / 1e6:,.1f} million"
    return f"{s}{a:,.0f}"


def article(word: str) -> str:
    """ "a 10-K", "an 8-K", "an S-1": the article as the form's name is spoken."""
    w = word.upper()
    vowel_sound = w[:1] in "AEFHILMNORSX" or w.startswith(("8", "11", "18"))
    return ("an " if vowel_sound else "a ") + word


def _link(text: str, url: str | None) -> str:
    return f"[{text}]({url})" if url and url.startswith("https://www.sec.gov/") else text


def build_profile(db: Session, cik: str, today: date | None = None) -> Profile | None:
    from app.services.intel import display_name

    today = today or date.today()
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        return None
    mart = db.get(MartCompany, cik)
    name = display_name(company.legal_name)
    cites: list[dict] = []

    def cite(label: str, url: str | None) -> int:
        for c in cites:
            if c["url"] == url and c["label"] == label:
                return c["n"]
        cites.append({"n": len(cites) + 1, "label": label, "url": url or ""})
        return len(cites)

    # Identity
    head = f"# {name}"
    if company.ticker:
        head += f" ({company.ticker}{', ' + company.exchange if company.exchange else ''})"
    facts = [f"CIK {company.cik}"]
    if company.sic_code:
        facts.append(
            f"industry SIC {company.sic_code}, {company.sic_description or ''}".rstrip(", ")
        )
    if company.state_of_incorporation:
        facts.append(f"incorporated in {company.state_of_incorporation}")
    if company.fiscal_year_end and company.fiscal_year_end[:2].isdigit():
        month = int(company.fiscal_year_end[:2])
        if 1 <= month <= 12:
            facts.append(f"fiscal year ends in {MONTHS[month - 1]}")
    lines = [head, "", "; ".join(facts) + "."]
    if mart and mart.first_filing_date:
        lines.append(
            f"Filings loaded here run from {mart.first_filing_date} to "
            f"{mart.latest_filing_date}; {mart.filings_last_12_months:,} in the last 12 months."
        )

    # Figures
    latest = json.loads(mart.latest_annual) if mart and mart.latest_annual else {}
    history = json.loads(mart.revenue_history) if mart and mart.revenue_history else []
    sentences: list[str] = []
    if latest:
        lines += [
            "",
            "## Latest annual figures",
            "",
            "| Figure | Value | Year | Source |",
            "|---|---|---|---|",
        ]
        for metric, label in PROFILE_METRICS:
            v = latest.get(metric)
            if not v:
                continue
            end = date.fromisoformat(v["period_end"])
            fy = periods.label(end, "annual", company.fiscal_year_end)
            source = f"{v['form_type']} filed {v['filed_date']}"
            lines.append(
                f"| {label} | {_money(v['value'])} | {fy}, ended {end} | "
                f"{_link(source, v.get('url'))} |"
            )
        rev = latest.get("revenue")
        if rev:
            n = cite(f"Revenue, {rev['form_type']} filed {rev['filed_date']}", rev.get("url"))
            end = date.fromisoformat(rev["period_end"])
            s = f"{name} reported revenue of {_money(rev['value'])} for the fiscal year ended {end}"
            if len(history) > 1 and history[1]["value"]:
                change = (
                    (history[0]["value"] - history[1]["value"]) / abs(history[1]["value"]) * 100
                )
                way = "up" if change > 0 else "down"
                s += f", {way} {abs(change):.1f}% from {_money(history[1]['value'])}"
            sentences.append(s + f" [{n}].")
        rest = [(label.lower(), latest[m]) for m, label in PROFILE_METRICS[1:] if latest.get(m)][:2]
        if rest:
            parts = []
            for label, v in rest:
                n = cite(
                    f"{label.capitalize()}, {v['form_type']} filed {v['filed_date']}", v.get("url")
                )
                verb = "were" if label.endswith("assets") else "was"
                parts.append(f"{label} {verb} {_money(v['value'])} [{n}]")
            sentences.append(" and ".join(parts).capitalize() + ".")
    if len(history) > 1:
        lines += ["", "## Revenue by fiscal year", ""]
        ends = [date.fromisoformat(h["period_end"]) for h in history]
        names = periods.labels(ends, "annual", company.fiscal_year_end)
        for label, h in zip(names, history, strict=True):
            lines.append(
                f"- {label}: {_money(h['value'])} "
                f"({_link(h['form_type'] + ' filed ' + str(h['filed_date']), h.get('url'))})"
            )

    # Going public
    if mart and mart.ipo_prospectus_date:
        lines += [
            "",
            "## Going public",
            "",
            "Final prospectus (Form 424B4) filed "
            + _link(str(mart.ipo_prospectus_date), mart.ipo_prospectus_url)
            + (
                f", after registering on Form {mart.first_registration_form} on "
                f"{mart.first_registration_date}."
                if mart.first_registration_date
                else "."
            ),
        ]
        if mart.ipo_prospectus_date >= today - timedelta(days=365):
            n = cite(f"424B4 filed {mart.ipo_prospectus_date}", mart.ipo_prospectus_url)
            subject = "It" if sentences else name
            sentences.append(
                f"{subject} filed its final IPO prospectus on {mart.ipo_prospectus_date} [{n}]."
            )

    # Leadership
    since = today - timedelta(days=365 * LEADERSHIP_YEARS)
    changes = db.scalars(
        select(OfficerChange)
        .where(OfficerChange.cik == cik, OfficerChange.filing_date >= since)
        .order_by(OfficerChange.filing_date.desc(), OfficerChange.seq)
        .limit(RECENT_CHANGES)
    ).all()
    if changes:
        lines += ["", "## Leadership changes, last two years", ""]
        for c in changes:
            who = ", ".join(x for x in (c.person, c.role) if x) or "An officer or director"
            what = c.what or c.change_type.replace("_", " ")
            lines.append(
                f"- {c.filing_date}: {who}: {what} ({_link('8-K item 5.02', c.source_url)})"
            )
        first = changes[0]
        n = cite(f"8-K item 5.02 filed {first.filing_date}", first.source_url)
        who = first.person or "an officer or director"
        subject = "Its" if sentences else f"{name}'s"
        sentences.append(
            f"{subject} latest leadership change, filed {first.filing_date}, concerns {who} [{n}]."
        )

    # Filings
    recent = db.scalars(
        select(Filing)
        .where(Filing.cik == cik)
        .order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
        .limit(RECENT_FILINGS)
    ).all()
    if recent:
        lines += ["", "## Recent filings", ""]
        for f in recent:
            items = split_items(f.items)
            about = "; ".join(f"item {i} {ITEM_TITLES.get(i, '')}".strip() for i in items[:2])
            lines.append(
                f"- {f.filing_date}: {_link(f.form_type, f.source_url)}"
                + (f" ({about})" if about else "")
            )
        top = recent[0]
        n = cite(f"{top.form_type} filed {top.filing_date}", top.source_url)
        subject = "Its" if sentences else f"{name}'s"
        sentences.append(
            f"{subject} most recent filing is {article(top.form_type)} on {top.filing_date} [{n}]."
        )

    lines += [
        "",
        "Figures are as reported in the company's filings; each links to its filing on sec.gov. "
        "Not investment advice.",
    ]
    if not sentences:
        sentences.append(f"{name} has no annual figures or filings loaded here yet.")
    return Profile(
        cik=cik,
        name=name,
        markdown="\n".join(lines) + "\n",
        summary=" ".join(sentences),
        citations=cites,
    )


_CITE = re.compile(r"\[(\d+)\]")


def summary_for(profile: Profile, cite) -> str:
    """The profile's summary with its citation numbers moved onto another list: `cite(label,
    url)` returns the number that list gives the source (the chat's brief, for one)."""
    moved = {c["n"]: cite(c["label"], c["url"]) for c in profile.citations}
    return _CITE.sub(lambda m: f"[{moved.get(int(m.group(1)), m.group(1))}]", profile.summary)


def store_profiles(db: Session, ciks: list[str] | None = None, log=None) -> int:
    """Rebuild company_documents (kind 'profile') for these companies, or every company."""
    scope = select(Company.cik)
    if ciks:
        scope = scope.where(Company.cik.in_(ciks))
    all_ciks = list(db.scalars(scope))
    if ciks:
        db.execute(delete(CompanyDocument).where(CompanyDocument.cik.in_(ciks)))
    else:
        db.execute(delete(CompanyDocument))
    now, rows, written = datetime.now(UTC), [], 0
    for cik in all_ciks:
        p = build_profile(db, cik)
        if p is None:
            continue
        rows.append(
            {
                "cik": cik,
                "kind": "profile",
                "title": p.name,
                "markdown": p.markdown,
                "built_at": now,
            }
        )
        if len(rows) >= 1000:
            db.execute(insert(CompanyDocument), rows)
            written += len(rows)
            rows = []
            if log:
                log(f"profiles: {written}/{len(all_ciks)}")
    if rows:
        db.execute(insert(CompanyDocument), rows)
        written += len(rows)
    db.commit()
    return written
