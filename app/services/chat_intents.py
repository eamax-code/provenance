"""C-06: chat intents for today's data, answered from stored data without a model: 13F holders,
segments, the auditor, insider signals, 5% holders (Schedules 13D/G) and the LEI. Every sentence
that states a figure cites its filing; with nothing stored the answer says so, with no figure.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InsiderActivity
from app.services.intel import Brief, display_name, money

INTENTS = (  # first match wins
    (
        "five_percent",
        re.compile(
            r"\b(5 ?%|five percent|13d|13g|beneficial owners?|"
            r"(?:more|over) than 5)",
            re.I,
        ),
    ),  # fmt: skip
    ("auditor", re.compile(r"\b(audit\w*|accounting firm|accountants?)\b", re.I)),
    ("lei", re.compile(r"\b(lei|legal entity identifier)\b", re.I)),
    (
        "insiders",
        re.compile(
            r"\b(insiders?|form 4|directors? (?:bought|sold)|officers? (?:bought|"
            r"sold))\b",
            re.I,
        ),
    ),  # fmt: skip
    (
        "segments",
        re.compile(
            r"\b(segments?|by (?:business|geograph\w*|region|product\w*|"
            r"division)|breakdown)\b",
            re.I,
        ),
    ),  # fmt: skip
    (
        "holders",
        re.compile(
            # "shareholders' equity" is a balance-sheet figure, not a holders question
            r"\b(institutional|13f|holders?(?!'?\s*equity)|shareholders?(?!'?\s*equity)|"
            r"who owns|owned by|fund managers?)\b",
            re.I,
        ),
    ),  # fmt: skip
)
INSIDER_DAYS = 365
NOT_SIGNALS = "This is information, not a signal, and not investment advice."


def detect(text: str) -> str | None:
    return next((name for name, rx in INTENTS if rx.search(text)), None)


def _name(b: Brief) -> str:
    c = b.company
    return display_name(c.legal_name, c.ticker, c.registrant_name)


def _cite(b: Brief, label: str, url: str | None) -> int | None:
    if not url:
        return None
    same = next((c["n"] for c in b.citations if c["url"] == url), None)
    return same or b.cite(label, url)


def holders(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import thirteenf
    from app.services.sec_client import filing_index_url

    block = thirteenf.for_company(db, b.company, as_of, top=5)
    if block is None:
        return f"The filings loaded here have no Form 13F holdings for {_name(b)}."
    parts = []
    for h in block["top_holders"]:
        url = h.get("filing_url") or filing_index_url(h["filer_cik"], h["accession_number"])
        n = _cite(b, f"13F of {h['name']}, filed {h['filing_date']}", url)
        parts.append(f"{h['name']} ({money(h['value_usd'], 'USD')}) [{n}]")
    text = (f"{block['holders_count']:,} institutional managers reported holding {_name(b)} on "
            f"Form 13F for the quarter ended {block['quarter']}. The largest by value: "
            + "; ".join(parts) + ".")  # fmt: skip
    if any("American depositary" in n for n in block.get("notes", [])):
        text += " Holdings are in American depositary shares, so no share percentage is given."
    return text


def five_percent(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import beneficial_owners

    rows = [h for h in beneficial_owners.holders(db, b.company.cik, as_of)
            if not h.get("below_threshold")][:5]  # fmt: skip
    if not rows:
        return (f"The filings loaded here have no Schedule 13D or 13G reporting 5% or more of "
                f"{_name(b)}.")  # fmt: skip
    parts = []
    for h in rows:
        n = _cite(b, f"Schedule {h['schedule']} filed {h['filing_date']}", h["source_url"])
        pct = f"{h['percent']:.1f}%" if h.get("percent") is not None else "percent not stated"
        parts.append(f"{h['name']} {pct} (Schedule {h['schedule']}, filed {h['filing_date']}) "
                     f"[{n}]")  # fmt: skip
    return f"Holders reporting 5% or more of {_name(b)}: " + "; ".join(parts) + "."


def auditor(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import auditors

    block = auditors.for_company(db, b.company.cik, as_of)
    if not block or not block.get("current"):
        return f"The annual reports loaded here do not name {_name(b)}'s auditor."
    cur, rep = block["current"], block["current"]["latest_report"]
    n = _cite(b, f"{rep['form_type']} filed {rep['filed_date']}", rep["source_url"])
    where = f" ({cur['location']})" if cur.get("location") else ""
    fy = f" for fiscal {rep['fiscal_year']}" if rep.get("fiscal_year") else ""
    text = (f"{_name(b)}'s auditor is {cur['name']}{where}, as named in its {rep['form_type']}"
            f"{fy} filed {rep['filed_date']} [{n}].")  # fmt: skip
    if block.get("firm_changes"):
        ch = block["firm_changes"][0]
        text += (f" The audit firm changed from {ch.get('from_firm') or ch.get('from')} to "
                 f"{ch.get('to_firm') or ch.get('to')}.")  # fmt: skip
    return text


def segments(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import segments as seg

    block = seg.for_company(db, b.company.cik, as_of)
    kinds = (block or {}).get("kinds") or []
    pick = next((k for k in kinds if k["kind"] == "business"), kinds[0] if kinds else None)
    if pick is None:
        return f"The annual reports loaded here have no segment figures for {_name(b)}."
    metric = "revenue" if "revenue" in pick["metrics"] else next(iter(pick["metrics"]))
    period = pick["periods"][0] if pick["periods"] else None  # newest first
    unit = pick["metrics"][metric].get("unit")
    parts = []
    for s in pick["segments"]:
        v = (s.get("values") or {}).get(metric, {}).get(period)
        if v is not None:
            parts.append(f"{s['label']} {money(v, unit)}")
    f = block["filing"]
    n = _cite(b, f"{f['form_type']} filed {f['filed_date']}", f["source_url"])
    if not parts:
        return f"{_name(b)}'s latest report has no {metric} by {pick['kind']} segment [{n}]."
    kind = {"business": "business segment", "geography": "geography"}.get(pick["kind"],
                                                                          pick["kind"])  # fmt: skip
    status = pick["metrics"][metric].get("status", {}).get(period)
    text = (f"{_name(b)}'s {metric.replace('_', ' ')} by {kind} for the fiscal year ended "
            f"{period}: " + "; ".join(parts) + f" [{n}].")  # fmt: skip
    if status == "unreconciled":
        text += " These do not add up to the consolidated figure, as the report tags them."
    return text


def insiders(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import insider_activity

    ref = as_of or date.today()
    since = ref - timedelta(days=INSIDER_DAYS)
    rows = list(db.scalars(
        select(InsiderActivity).where(InsiderActivity.cik == b.company.cik,
                                      InsiderActivity.filing_date <= ref,
                                      InsiderActivity.filing_date >= since)
        .order_by(InsiderActivity.filing_date.desc()).limit(5)
    ))  # fmt: skip
    if not rows:
        return (f"No insider buying or large selling at {_name(b)} stands out in the Forms 4 "
                f"loaded here for the last year. {NOT_SIGNALS}")  # fmt: skip
    parts = []
    for r in rows:
        n = _cite(b, f"Form 4 filed {r.filing_date}", r.source_url)
        parts.append(f"{r.filing_date}: {insider_activity.label(r)} [{n}]")
    return (f"Insider activity at {_name(b)} in the last year (Forms 4): " + "; ".join(parts)
            + f". {NOT_SIGNALS}")  # fmt: skip


METHODS = {"sec": "the LEI the company reports to the SEC",
           "name_jurisdiction": "its legal name and jurisdiction in GLEIF"}  # fmt: skip


def lei(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import identity

    block = identity.for_company(db, b.company.cik)
    if not block or not block.get("lei"):
        return f"No LEI is linked to {_name(b)} in the data loaded here."
    # only sec.gov/Archives filings are ever linked: GLEIF is named, not linked (PM, 2026-11-23)
    n = b.cite(f"GLEIF public record, LEI {block['lei']}, CC0 golden copy", None)
    how = METHODS.get(block["match_method"], f"matching ({block['match_method']})")
    holder = f" ({block['lei_name']})" if block.get("lei_name") else ""
    return f"{_name(b)}'s LEI is {block['lei']}{holder}, matched by {how} [{n}]."


HOW = {  # the endpoint that returns the same data (C-01 "how I got this")
    "holders": "ownership", "five_percent": "holders", "auditor": "overview",
    "segments": "segments", "insiders": "insider-transactions", "lei": "overview",
}  # fmt: skip

ANSWERS = {"holders": holders, "five_percent": five_percent, "auditor": auditor,
           "segments": segments, "insiders": insiders, "lei": lei}  # fmt: skip


def answer(db: Session, b: Brief, intent: str, as_of: date | None) -> str:
    return ANSWERS[intent](db, b, as_of)


# C-03: grounded follow-ups. Each is offered only when the data that answers it is stored, so a
# suggestion never leads to "not in the filings loaded here".
def follow_ups(db: Session, b: Brief, current: str | None, limit: int = 3) -> list[str]:
    from sqlalchemy import exists

    from app.db.models import CompanyAuditor, CompanySegment, Filing, FinancialFact, Holding13F
    from app.services import cusips, intel

    c, name = b.company, _name(b)
    has = lambda q: bool(db.scalar(select(exists(q))))  # noqa: E731
    out: list[tuple[str, str]] = []
    revenue = intel.annual_series(db, c.cik, "revenue", b.as_of)
    if len(revenue) >= 2:
        out.append(("trend", f"How has {name}'s revenue changed?"))
    op = intel.annual_series(db, c.cik, "operating_income", b.as_of)
    if revenue and op and op[0].period_end == revenue[0].period_end:
        out.append(("figure", f"What is {name}'s operating margin?"))
    codes = [x.cusip for x in cusips.cusips_for(db, c.cik)]
    if codes and has(select(Holding13F.cusip).where(Holding13F.cusip.in_(codes))):
        out.append(("holders", f"Who are {name}'s largest institutional holders?"))
    if has(select(CompanySegment.cik).where(CompanySegment.cik == c.cik)):
        out.append(("segments", f"What is {name}'s revenue by segment?"))
    if has(select(CompanyAuditor.cik).where(CompanyAuditor.cik == c.cik)):
        out.append(("auditor", f"Who audits {name}?"))
    if has(select(Filing.cik).where(Filing.cik == c.cik, Filing.items.like("%5.02%"))):
        out.append(("leadership", f"Any officer changes at {name}?"))
    if not out and has(select(FinancialFact.cik).where(FinancialFact.cik == c.cik)):
        out.append(("summary", f"Summarize {name}"))
    return [q for kind, q in out if kind != current][:limit]
