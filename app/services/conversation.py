"""The chat's conversation flow (issue #7): named intents across companies, a small context carried
from one answer to the next, and answers read straight from the marts (issue #8).

Designed with the chatbot-flow-design skill's structured-guided pattern: every intent below has a
scope and a data source, follow-ups resolve against the previous answer, and anything outside the
intents falls back to the company flow or a short statement of what the chat covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, MartCompany, MartFilingActivity
from app.services.marts import loads

MAX_LIST = 200
TABLE_ROWS = 50
BLANK_CHECK_SIC = "6770"
DEFAULT_WINDOW_DAYS = 182


class ConversationContext(BaseModel):
    """What the previous answer was about; the page sends it back with the next question."""

    intent: str | None = Field(None, max_length=40)
    cik: str | None = Field(None, max_length=10)
    ciks: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    label: str | None = Field(None, max_length=200)


class Exchange(BaseModel):
    """One earlier question and its answer, for the model's sense of the conversation."""

    q: str = Field(max_length=500)
    a: str = Field("", max_length=1200)


@dataclass
class Plan:
    kind: str
    days: int = DEFAULT_WINDOW_DAYS
    window_label: str = "the last 6 months"
    form: str | None = None
    metric: str = "revenue"
    years: int = 3
    limit: int = 10
    order: str = "desc"


@dataclass
class DataAnswer:
    answer: str
    intent: str
    widgets: list[dict] = field(default_factory=list)
    context: ConversationContext | None = None
    notes: list[str] = field(default_factory=list)


_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "eighteen": 18, "twenty": 20,
}  # fmt: skip
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30.44, "quarter": 91.3, "year": 365.25}
_WINDOW = re.compile(
    r"\b(?:last|past|previous|recent)\s+(\d+|[a-z]+)?\s*(day|week|month|quarter|year)s?\b"
    r"|\bthis\s+(week|month|quarter|year)\b|\b(today|yesterday)\b",
    re.IGNORECASE,
)
_REFERS_BACK = re.compile(
    r"\b(these|those|them|their|they|the same|that list|this list|the list|above|"
    r"each of them|all of them|which ones?)\b",
    re.IGNORECASE,
)
_IPO = re.compile(
    r"\b((?:new|recent|latest)\s+(?:us\s+)?(?:listings?|ipos?|public companies)|newly listed|"
    r"ipos?|initial public offerings?|went public|go(?:ne|ing)? public|debut(?:ed|s)?)\b",
    re.IGNORECASE,
)
_RANK = re.compile(r"\b(largest|biggest|top|highest|most|smallest|lowest|leading)\b", re.IGNORECASE)
_FORM = re.compile(
    r"\b(10-K|10-Q|8-K|S-1|F-1|20-F|40-F|424B4|DEF 14A|13D|13G|SC 13D|SC 13G|S-3|6-K)\b",
    re.IGNORECASE,
)
_FILED = re.compile(r"\b(filed?|filings?|filers?|submitted)\b", re.IGNORECASE)
_HOW_MANY = re.compile(r"\bhow many\b", re.IGNORECASE)
_OUT_OF_SCOPE = re.compile(
    r"\b(stock|share) price|\bprice target|\bshould i (buy|sell|invest)|\bbuy or sell\b|"
    r"\b(buy|sell) (the )?(stock|shares)\b|\bmarket cap(italization)?\b|\bdividend yield\b|"
    r"\bstock tips?\b",
    re.IGNORECASE,
)
_METRICS = (
    ("net_income", re.compile(r"\b(net income|profits?|earnings|net loss)\b", re.IGNORECASE)),
    ("total_assets", re.compile(r"\b(total )?assets\b", re.IGNORECASE)),
    ("operating_income", re.compile(r"\boperating income\b", re.IGNORECASE)),
    ("operating_cash_flow", re.compile(r"\b(operating )?cash flow\b", re.IGNORECASE)),
    ("revenue", re.compile(r"\b(revenue|sales|turnover|top line)\b", re.IGNORECASE)),
)
METRIC_LABELS = {
    "revenue": "Revenue",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "operating_income": "Operating income",
    "operating_cash_flow": "Operating cash flow",
}


def plan(text: str, ctx: ConversationContext | None) -> Plan | None:
    """The cross-company intent a question names, or None for the company flow."""
    if _OUT_OF_SCOPE.search(text):
        return Plan("out_of_scope")
    days, window_label = _window(text)
    metric = _metric(text)
    years = _years(text)
    if ctx and ctx.ciks and _REFERS_BACK.search(text):
        return Plan("list_followup", metric=metric or "revenue", years=years or 3)
    if _IPO.search(text):
        return Plan("ipos", days=days, window_label=window_label)
    form = _FORM.search(text)
    if form and _FILED.search(text):
        kind = (
            "filing_count" if _HOW_MANY.search(text) and "compan" not in text.lower() else "filers"
        )
        return Plan(kind, days=days, window_label=window_label, form=form.group(1).upper())
    rank = _RANK.search(text)
    if rank and metric and re.search(r"\bcompan(y|ies)\b", text, re.IGNORECASE):
        low = rank.group(1).lower() in ("smallest", "lowest")
        return Plan("rank", metric=metric, limit=_top_n(text), order="asc" if low else "desc")
    return None


def answer(db: Session, p: Plan, ctx: ConversationContext | None, today: date) -> DataAnswer:
    if p.kind == "out_of_scope":
        return DataAnswer(
            "I can't help with share prices or buy and sell decisions. I answer from SEC filings: "
            "a company's reported figures and trends, leadership changes, filings, prospectuses, "
            "and lists such as recent IPOs or the largest companies by revenue.",
            "out_of_scope",
        )
    if p.kind == "ipos":
        return _ipos(db, p, today)
    if p.kind == "filers":
        return _filers(db, p, today)
    if p.kind == "filing_count":
        return _filing_count(db, p, today)
    if p.kind == "rank":
        return _rank(db, p)
    if p.kind == "list_followup":
        return _list_table(db, p, ctx)
    raise ValueError(p.kind)


# ---- intents -------------------------------------------------------------------------------


def _ipos(db: Session, p: Plan, today: date) -> DataAnswer:
    since = today - timedelta(days=p.days)
    rows = db.scalars(
        select(MartCompany)
        .where(
            MartCompany.ipo_prospectus_date >= since,
            MartCompany.first_registration_date.is_not(None),
            MartCompany.first_registration_date
            >= MartCompany.ipo_prospectus_date - timedelta(days=730),
        )
        .order_by(MartCompany.ipo_prospectus_date.desc(), MartCompany.legal_name)
    ).all()
    n = len(rows)
    if not n:
        return DataAnswer(
            f"No company filed a final IPO prospectus (Form 424B4) {_when(p)}.", "ipos"
        )
    spacs = sum(1 for r in rows if r.sic_code == BLANK_CHECK_SIC)
    recent = ", ".join(_name(r) for r in rows[:3])
    text = (
        f"{n} {_plural(n, 'company', 'companies')} went public {_when(p)}, going by the "
        f"final IPO prospectus (Form 424B4) each filed after registering on Form S-1 or F-1."
    )
    if spacs:
        text += f" {spacs} of them are blank-check companies (SPACs)."
    text += f" The most recent are {recent}."
    widget = _table(
        f"Went public {_when(p)}",
        ["Company", "Ticker", "IPO prospectus", "Registered", "Latest annual revenue"],
        [
            [
                _cell(_name(r)),
                _cell(r.ticker or "—"),
                _cell(_d(r.ipo_prospectus_date), r.ipo_prospectus_url),
                _cell(f"{r.first_registration_form} {_d(r.first_registration_date)}"),
                _revenue_cell(r),
            ]
            for r in rows[:TABLE_ROWS]
        ],
        note=_more(n),
    )
    return DataAnswer(
        text,
        "ipos",
        [widget],
        ConversationContext(
            intent="ipos",
            ciks=[r.cik for r in rows[:MAX_LIST]],
            label=f"companies that went public {_when(p)}",
        ),
        [
            "A 424B4 is the final prospectus filed when an offering prices. It marks an IPO on "
            "paper; it does not confirm that trading began."
        ],
    )


def _filers(db: Session, p: Plan, today: date) -> DataAnswer:
    since = today - timedelta(days=p.days)
    filed = (
        select(Filing.cik, func.max(Filing.filing_date).label("last"), func.count().label("n"))
        .where(Filing.form_type == p.form, Filing.filing_date >= since)
        .group_by(Filing.cik)
        .subquery()
    )
    rows = db.execute(
        select(MartCompany, filed.c.last, filed.c.n)
        .join(filed, filed.c.cik == MartCompany.cik)
        .order_by(filed.c.last.desc(), MartCompany.legal_name)
    ).all()
    n = len(rows)
    if not n:
        return DataAnswer(f"No company filed a {p.form} {_when(p)}.", "filers")
    text = (
        f"{n} {_plural(n, 'company', 'companies')} filed a {p.form} {_when(p)}. The most "
        f"recent are {', '.join(_name(r[0]) for r in rows[:3])}."
    )
    widget = _table(
        f"{p.form} filers, {p.window_label}",
        ["Company", "Ticker", "Latest " + p.form, "Filings"],
        [
            [_cell(_name(m)), _cell(m.ticker or "—"), _cell(_d(last)), _cell(str(k))]
            for m, last, k in rows[:TABLE_ROWS]
        ],
        note=_more(n),
    )
    return DataAnswer(
        text,
        "filers",
        [widget],
        ConversationContext(
            intent="filers",
            ciks=[m.cik for m, _, _ in rows[:MAX_LIST]],
            label=f"companies that filed a {p.form} {_when(p)}",
        ),
    )


def _filing_count(db: Session, p: Plan, today: date) -> DataAnswer:
    since = today - timedelta(days=p.days)
    first_month = since.replace(day=1)
    filings, companies = db.execute(
        select(
            func.coalesce(func.sum(MartFilingActivity.filings), 0),
            func.coalesce(func.max(MartFilingActivity.companies), 0),
        ).where(MartFilingActivity.form_type == p.form, MartFilingActivity.month >= first_month)
    ).one()
    exact = db.scalar(
        select(func.count()).where(Filing.form_type == p.form, Filing.filing_date >= since)
    )
    n = int(exact if exact is not None else filings)
    return DataAnswer(
        f"{n:,} {p.form} {_plural(n, 'filing was', 'filings were')} filed {_when(p)} "
        f"by the companies loaded here.",
        "filing_count",
    )


def _rank(db: Session, p: Plan) -> DataAnswer:
    label = METRIC_LABELS[p.metric]
    if p.metric == "revenue":
        order = (
            MartCompany.latest_revenue.asc()
            if p.order == "asc"
            else MartCompany.latest_revenue.desc()
        )
        rows = db.scalars(
            select(MartCompany)
            .where(MartCompany.latest_revenue.is_not(None), MartCompany.latest_revenue > 0)
            .order_by(order)
            .limit(p.limit)
        ).all()
        values = [(r, (loads(r.revenue_history) or [None])[0]) for r in rows]
    else:
        # Other metrics live in the JSON column; rank the companies with revenue first.
        pool = db.scalars(select(MartCompany).where(MartCompany.latest_annual.is_not(None))).all()
        scored = [(r, (loads(r.latest_annual) or {}).get(p.metric)) for r in pool]
        scored = [(r, v) for r, v in scored if v and v.get("value") is not None]
        scored.sort(key=lambda x: x[1]["value"], reverse=p.order != "asc")
        values = scored[: p.limit]
    if not values:
        return DataAnswer(f"No company has a reported annual {label.lower()} loaded yet.", "rank")
    word = "smallest" if p.order == "asc" else "largest"
    top = values[0]
    text = (
        f"{_name(top[0])} has the {word} latest annual {label.lower()}, {_money(top[1]['value'])} "
        f"for the year ended {top[1]['period_end']}. Fiscal years differ, so compare the period "
        f"ends in the table."
    )
    widget = _table(
        f"{word.capitalize()} by latest annual {label.lower()}",
        ["Company", "Ticker", label, "Year ended", "Source"],
        [
            [
                _cell(_name(r)),
                _cell(r.ticker or "—"),
                _cell(_money(v["value"])),
                _cell(v["period_end"]),
                _cell(f"{v['form_type']} {v['filed_date']}", v.get("url")),
            ]
            for r, v in values
        ],
    )
    return DataAnswer(
        text,
        "rank",
        [widget],
        ConversationContext(
            intent="rank",
            ciks=[r.cik for r, _ in values],
            label=f"the {word} companies by {label.lower()}",
        ),
    )


def _list_table(db: Session, p: Plan, ctx: ConversationContext | None) -> DataAnswer:
    ciks = list(ctx.ciks) if ctx else []
    rows = {r.cik: r for r in db.scalars(select(MartCompany).where(MartCompany.cik.in_(ciks)))}
    # Companies with figures first, in the previous answer's order; the rest after them.
    listed = [rows[c] for c in ciks if c in rows]
    ordered = [r for r in listed if _series(r, p.metric)] + [
        r for r in listed if not _series(r, p.metric)
    ]
    label = METRIC_LABELS[p.metric]
    years = max(1, min(p.years, 5))
    table_rows, with_data = [], 0
    for r in ordered[:TABLE_ROWS]:
        series = _series(r, p.metric)[:years]
        if series:
            with_data += 1
        cells = [_cell(_name(r)), _cell(r.ticker or "—")]
        for k in range(years):
            v = series[k] if k < len(series) else None
            cells.append(
                _cell(f"{_money(v['value'])} (FY ended {v['period_end']})", v.get("url"))
                if v
                else _cell("—")
            )
        table_rows.append(cells)
    n = len(ordered)
    about = ctx.label if ctx and ctx.label else "companies in the previous answer"
    shown = min(n, TABLE_ROWS)
    text = f"{label} for the {n} {about}, up to {years} fiscal years each"
    text += f" (the first {shown} are in the table)." if n > shown else "."
    missing = shown - with_data
    if missing:
        text += (
            f" {missing} of {'those' if n > shown else 'them'} have no annual report with "
            f"{label.lower()} yet; newly public companies report it first in their prospectus, "
            "so ask about one by name to read it."
        )
    widget = _table(
        f"{label}, last {years} fiscal years",
        ["Company", "Ticker"]
        + [
            ("Latest year" if k == 0 else f"{k} year{'s' if k > 1 else ''} earlier")
            for k in range(years)
        ],
        table_rows,
        note=_more(n),
    )
    return DataAnswer(
        text,
        "list_followup",
        [widget],
        ConversationContext(intent="list_followup", ciks=ciks, label=about),
    )


# ---- helpers -------------------------------------------------------------------------------


def _series(r: MartCompany, metric: str) -> list[dict]:
    if metric == "revenue":
        return loads(r.revenue_history) or []
    latest = (loads(r.latest_annual) or {}).get(metric)
    return [latest] if latest else []


def _revenue_cell(r: MartCompany) -> dict:
    v = (loads(r.revenue_history) or [None])[0]
    if not v:
        return _cell("no annual report yet" if not r.latest_annual_report_date else "—")
    return _cell(f"{_money(v['value'])} (FY ended {v['period_end']})", v.get("url"))


def _table(title: str, columns: list[str], rows: list[list[dict]], note: str | None = None) -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows, "note": note}


def _cell(text: str, url: str | None = None) -> dict:
    # Links go only to filings on sec.gov.
    if url and url.startswith("https://www.sec.gov/"):
        return {"text": text, "url": url}
    return {"text": text}


def _more(n: int) -> str | None:
    return f"Showing {TABLE_ROWS} of {n}." if n > TABLE_ROWS else None


def _name(r) -> str:
    from app.services.intel import display_name

    return display_name(r.legal_name)


def _d(d: date | None) -> str:
    return d.isoformat() if d else "—"


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    a, s = abs(v), "-$" if v < 0 else "$"
    if a >= 1e9:
        return f"{s}{a / 1e9:,.1f} billion"
    if a >= 1e6:
        return f"{s}{a / 1e6:,.1f} million"
    return f"{s}{a:,.0f}"


def _when(p: Plan) -> str:
    label = p.window_label
    return label if label.startswith(("this ", "today", "yesterday")) else f"in {label}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _window(text: str) -> tuple[int, str]:
    m = _WINDOW.search(text)
    if not m:
        return DEFAULT_WINDOW_DAYS, "the last 6 months"
    if m.group(4):
        return (0 if m.group(4).lower() == "today" else 1), m.group(4).lower()
    if m.group(3):
        # "This year" starts on January 1, "this week" on Monday.
        unit, today = m.group(3).lower(), date.today()
        start = {
            "week": today - timedelta(days=today.weekday()),
            "month": today.replace(day=1),
            "quarter": today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1),
            "year": today.replace(month=1, day=1),
        }[unit]
        return (today - start).days, f"this {unit}"
    raw, unit = (m.group(1) or "1").lower(), m.group(2).lower()
    count = int(raw) if raw.isdigit() else _NUMBERS.get(raw, 1)
    count = max(1, min(count, 120))
    days = int(round(count * _UNIT_DAYS[unit]))
    return days, (f"the last {unit}" if count == 1 else f"the last {count} {unit}s")


def _metric(text: str) -> str | None:
    for metric, pattern in _METRICS:
        if pattern.search(text):
            return metric
    return None


def _years(text: str) -> int | None:
    m = re.search(r"\b(\d+|[a-z]+)\s+(?:fiscal\s+)?years?\b", text, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).lower()
    n = int(raw) if raw.isdigit() else _NUMBERS.get(raw)
    return max(1, min(n, 5)) if n else None


def _top_n(text: str) -> int:
    m = re.search(r"\btop\s+(\d+|[a-z]+)\b", text, re.IGNORECASE)
    if m:
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else _NUMBERS.get(raw, 10)
        return max(1, min(n, 50))
    return 10


def strongly_named(db: Session, text: str) -> Company | None:
    """A company the question names clearly (ticker in capitals, CIK, or a capitalised name):
    such a question stays on that company even if it also says "filings" or "IPO"."""
    from app.services.intel import resolve_company

    return resolve_company(db, text, follow_up=True)
