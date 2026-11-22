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
from sqlalchemy.orm import Session, object_session

from app.db.models import Company, Filing, MartCompany, MartCompanyPeriod, MartFilingActivity
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
    ciks: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)  # C-04: a screen's parsed criteria


@dataclass
class DataAnswer:
    answer: str
    intent: str
    widgets: list[dict] = field(default_factory=list)
    context: ConversationContext | None = None
    notes: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)  # {n, label, url}: each figure's filing
    facts: list = field(default_factory=list)  # C-01: (fact, citation n) behind each figure chip
    how: list[dict] = field(default_factory=list)  # C-01: the API calls that answer it
    names: dict = field(default_factory=dict)  # C-01: {cik: display name} for the chips


def _cite(cites: list[dict], label: str, url: str | None) -> int | None:
    """The citation number for a filing link (sec.gov/Archives only), added once."""
    if not url or "sec.gov/Archives" not in url:
        return None
    same = next((c["n"] for c in cites if c["url"] == url), None)
    if same:
        return same
    cites.append({"n": len(cites) + 1, "label": label, "url": url})
    return len(cites)


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
_COMPARE = re.compile(r"\b(compare|comparison|compared|versus|vs\.?|against)\b", re.IGNORECASE)
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


# C-04: screens in words ("software companies over $1B revenue with operating margin above
# 20%"). Industries map to SEC SIC code ranges; sizes and margins come from each company's
# latest annual figures (US-dollar reporters: sizes compare in one currency).
INDUSTRIES = {
    "software": ("7370", "7379"), "semiconductor": ("3674", "3674"), "bank": ("6020", "6199"),
    "insurance": ("6300", "6411"), "insurer": ("6300", "6411"), "pharma": ("2833", "2836"),
    "biotech": ("2833", "2836"), "oil": ("1311", "1389"), "utilit": ("4900", "4991"),
    "reit": ("6798", "6798"), "retail": ("5200", "5999"), "airline": ("4512", "4513"),
    "automaker": ("3711", "3711"), "restaurant": ("5812", "5812"), "telecom": ("4812", "4899"),
}  # fmt: skip
_INDUSTRY = re.compile(r"\b(" + "|".join(INDUSTRIES) + r")\w*", re.IGNORECASE)
_SIZE = re.compile(
    r"\b(?:over|above|more than|at least|exceeding|>)\s*\$?\s*(\d+(?:\.\d+)?)\s*"
    r"(trillion|billion|bn|b|million|mn|m)\b(?:\s+(?:in|of))?\s*(?:annual\s+)?"
    r"(revenue|sales|net income|profit)?",
    re.IGNORECASE,
)
_MARGIN_MIN = re.compile(
    r"\b(gross|operating|net|profit)\s+margins?\s*(?:of\s+)?(?:above|over|more than|at least|"
    r"greater than|>|exceeding)\s*(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_SCALE = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6,
          "m": 1e6}  # fmt: skip


def screen_filters(text: str) -> dict:
    """The criteria a screen question names; empty when it names none."""
    f: dict = {}
    ind = _INDUSTRY.search(text)
    if ind:
        key = next(k for k in INDUSTRIES if ind.group(1).lower().startswith(k))
        f["industry"], f["sic_range"] = key, list(INDUSTRIES[key])
    size = _SIZE.search(text)
    if size:
        what = (size.group(3) or "revenue").lower()
        metric = "net_income" if what in ("net income", "profit") else "revenue"
        f[f"min_{metric}_usd"] = float(size.group(1)) * _SCALE[size.group(2).lower()]
    m = _MARGIN_MIN.search(text)
    if m:
        kind = "net" if m.group(1).lower() == "profit" else m.group(1).lower()
        f[f"min_{kind}_margin_pct"] = float(m.group(2))
    return f


def plan(text: str, ctx: ConversationContext | None, db: Session | None = None) -> Plan | None:
    """The cross-company intent a question names, or None for the company flow."""
    if _OUT_OF_SCOPE.search(text):
        return Plan("out_of_scope")
    if db is not None and _COMPARE.search(text):
        named = compared_companies(db, text)
        if len(named) >= 2:
            from app.services.intel import asked_margin

            margin = asked_margin(text)
            return Plan(
                "compare",
                metric=f"margin:{margin}" if margin else (_metric(text) or "revenue"),
                years=_years(text) or 3,
                ciks=[c.cik for c in named],
            )
    filters = screen_filters(text)
    if len(filters) >= 2 or (filters and re.search(r"\bcompan(y|ies)\b|\bwhich\b|\blist\b",
                                                   text, re.IGNORECASE)):  # fmt: skip
        return Plan("screen", filters=filters)
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
    if p.kind == "compare":
        return _compare(db, p)
    if p.kind == "screen":
        return _screen(db, p)
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
    cites: list[dict] = []

    def named(r) -> str:  # each company with its own final prospectus cited (C-07)
        n = _cite(cites, f"{_name(r)}, 424B4 filed {_d(r.ipo_prospectus_date)}",
                  r.ipo_prospectus_url)  # fmt: skip
        return f"{_name(r)} [{n}]" if n else _name(r)

    recent = ", ".join(named(r) for r in rows[:3])
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
        citations=cites,
        how=[{"endpoint": "/v1/ipos", "parameters": {"days": p.days}}],
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
            .where(
                MartCompany.latest_revenue.is_not(None),
                MartCompany.latest_revenue > 0,
                MartCompany.reporting_currency == "USD",
            )  # sizes compare in one currency
            .order_by(order)
            .limit(p.limit)
        ).all()
        values = [(r, (loads(r.revenue_history) or [None])[0]) for r in rows]
    else:
        # Other metrics live in the JSON column; rank the companies with revenue first.
        usd = MartCompany.reporting_currency == "USD"  # sizes compare in one currency
        has = MartCompany.latest_annual.is_not(None)
        pool = db.scalars(select(MartCompany).where(has, usd)).all()
        scored = [(r, (loads(r.latest_annual) or {}).get(p.metric)) for r in pool]
        scored = [(r, v) for r, v in scored if v and v.get("value") is not None]
        scored.sort(key=lambda x: x[1]["value"], reverse=p.order != "asc")
        values = scored[: p.limit]
    if not values:
        return DataAnswer(f"No company has a reported annual {label.lower()} loaded yet.", "rank")
    word = "smallest" if p.order == "asc" else "largest"
    top = values[0]
    amount = _money(top[1]["value"], top[1].get("unit"))
    cites: list[dict] = []
    n = _cite(cites, f"{_name(top[0])}, {label.lower()}", top[1].get("url"))
    figure = (f", {amount} for the year ended {top[1]['period_end']} [{n}]," if n
              else f" (year ended {top[1]['period_end']}),")  # fmt: skip
    text = (
        f"{_name(top[0])} has the {word} latest annual {label.lower()}{figure} among companies "
        f"reporting in US dollars (other currencies are not converted). Fiscal years differ, so "
        f"compare the period ends in the table."
    )
    widget = _table(
        f"{word.capitalize()} by latest annual {label.lower()}",
        ["Company", "Ticker", label, "Year ended", "Source"],
        [
            [
                _cell(_name(r)),
                _cell(r.ticker or "—"),
                _cell(_money(v["value"], v.get("unit"))),
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
        citations=cites,
        how=[
            {"endpoint": "/v1/facts/screen", "parameters": {"metric": p.metric, "limit": p.limit}}
        ],  # fmt: skip
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
                _cell(
                    f"{_money(v['value'], v.get('unit'))} (FY ended {v['period_end']})",
                    v.get("url"),
                )
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


def _compare(db: Session, p: Plan) -> DataAnswer:
    """Each company's latest annual figure (or margin) from its own filing, cited (C-07)."""
    from app.services import intel

    comps = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(p.ciks)))}
    cites: list[dict] = []
    facts: list = []
    margin = p.metric.split(":", 1)[1] if p.metric.startswith("margin:") else None
    label = f"{margin} margin" if margin else METRIC_LABELS[p.metric].lower()
    parts, ends = [], set()
    for cik in p.ciks:
        c = comps.get(cik)
        if c is None:
            continue
        name = intel.display_name(c.legal_name, c.ticker, c.registrant_name)
        if margin:
            top = intel.annual_fact(db, c, "revenue", None, None)
            part = intel._MARGIN_PARTS[margin]
            same = intel.annual_series(db, cik, part, None)
            num = top and next(
                (f for f in same if f.period_end == top.period_end and f.unit == top.unit), None
            )
            if top is None or num is None or not top.value:
                parts.append(f"{name}: not available from the filings loaded here")
                continue
            n = _cite(cites, f"{name}, {top.form_type} filed {top.filed_date}", top.source_url)
            facts += [(num, n), (top, n)]
            pct = float(num.value) / float(top.value) * 100
            parts.append(f"{name} {pct:.1f}% (year ended {top.period_end}) [{n}]")
            ends.add(top.period_end.isoformat()[5:])
            continue
        f = intel.annual_fact(db, c, p.metric, None, None)
        if f is None:
            parts.append(f"{name} not reported")
            continue
        n = _cite(cites, f"{name}, {f.form_type} filed {f.filed_date}", f.source_url)
        facts.append((f, n))
        parts.append(f"{name} {intel.display(f.value, p.metric, f.unit)} (year ended "
                     f"{f.period_end}) [{n}]")  # fmt: skip
        ends.add(f.period_end.isoformat()[5:])
    text = f"Latest annual {label}: " + "; ".join(parts) + "."
    if margin:
        text += f" Each margin is {label.split()[0]} income over revenue, derived from the filing."
    if len(ends) > 1:
        text += " Their fiscal years end in different months, so the years do not line up exactly."
    widgets = []
    if not margin:
        table = _list_table(
            db,
            Plan("list_followup", metric=p.metric, years=p.years),
            ConversationContext(intent="compare", ciks=p.ciks, label="companies compared"),
        )
        n_years = max(1, min(p.years, 5))
        table.widgets[0]["title"] = f"{METRIC_LABELS[p.metric]}, last {n_years} fiscal years"
        widgets = table.widgets
    return DataAnswer(
        text,
        "compare",
        widgets,
        ConversationContext(intent="compare", ciks=p.ciks, label="the companies compared"),
        citations=cites,
        facts=facts,
        names={
            c.cik: intel.display_name(c.legal_name, c.ticker, c.registrant_name)
            for c in comps.values()
        },
        how=[
            {
                "endpoint": f"/v1/companies/{cik}/facts",
                "parameters": {
                    "metric": f"{margin}_margin" if margin else p.metric,
                    "period": "annual",
                },
            }
            for cik in p.ciks
        ],
    )


def _screen(db: Session, p: Plan) -> DataAnswer:
    """C-04: the companies matching a screen's criteria, from each one's latest annual figures,
    every figure cited to its filing; the parsed criteria are returned to show and edit."""
    from app.services.intel import money

    f = p.filters
    q = select(MartCompany).where(MartCompany.reporting_currency == "USD",
                                  MartCompany.latest_annual.is_not(None))  # fmt: skip
    if "sic_range" in f:
        lo, hi = f["sic_range"]
        q = q.where(MartCompany.sic_code >= lo, MartCompany.sic_code <= hi)
    rows = []
    for r in db.scalars(q):
        latest = loads(r.latest_annual) or {}
        rev, op = latest.get("revenue"), latest.get("operating_income")
        gp, ni = latest.get("gross_profit"), latest.get("net_income")
        if not rev or not rev.get("value"):
            continue
        margins = {}
        for kind, part in (("operating", op), ("gross", gp), ("net", ni)):
            if (
                part
                and part.get("value") is not None
                and part.get("period_end") == rev["period_end"]
            ):
                margins[kind] = part["value"] / rev["value"] * 100
        ok = True
        if rev["value"] < f.get("min_revenue_usd", float("-inf")):
            ok = False
        if f.get("min_net_income_usd") is not None and (
            not ni or ni.get("value") is None or ni["value"] < f["min_net_income_usd"]
        ):
            ok = False
        for kind in ("operating", "gross", "net"):
            need = f.get(f"min_{kind}_margin_pct")
            if need is not None and (kind not in margins or margins[kind] <= need):
                ok = False
        if ok:
            rows.append((r, rev, margins))
    rows.sort(key=lambda x: -x[1]["value"])
    crit = []
    if "industry" in f:
        crit.append(f"{f['industry']} (SIC {f['sic_range'][0]}-{f['sic_range'][1]})")
    if "min_revenue_usd" in f:
        crit.append(f"revenue over {money(f['min_revenue_usd'], 'USD')}")
    if "min_net_income_usd" in f:
        crit.append(f"net income over {money(f['min_net_income_usd'], 'USD')}")
    for kind in ("operating", "gross", "net"):
        if f"min_{kind}_margin_pct" in f:
            crit.append(f"{kind} margin above {f[f'min_{kind}_margin_pct']:g}%")
    scope = ("US-dollar reporters by their latest annual report; the country of the company "
             "is not filtered")  # fmt: skip
    cites: list[dict] = []
    if not rows:
        text = f"No company matches {', '.join(crit)} ({scope})."
    else:
        parts = []
        for r, rev, margins in rows[:3]:
            n = _cite(cites, f"{_name(r)}, annual report", rev.get("url"))
            m = f", operating margin {margins['operating']:.1f}%" if "operating" in margins else ""
            parts.append(f"{_name(r)} {money(rev['value'], 'USD')} revenue{m} [{n}]" if n
                         else _name(r))  # fmt: skip
        text = (f"{len(rows)} {_plural(len(rows), 'company matches', 'companies match')} "
                f"{', '.join(crit)} ({scope}). The largest by revenue: " + "; ".join(parts)
                + ".")  # fmt: skip
    widget = _table(
        f"Screen: {', '.join(crit)}",
        ["Company", "Ticker", "Revenue", "Operating margin", "Year ended"],
        [[_cell(_name(r)), _cell(r.ticker or "—"),
          _cell(money(rev["value"], "USD"), rev.get("url")),
          _cell(f"{margins['operating']:.1f}%" if "operating" in margins else "—"),
          _cell(rev["period_end"])] for r, rev, margins in rows[:TABLE_ROWS]],
        note=_more(len(rows)),
    )  # fmt: skip
    screen = {"type": "screen", "parameters": f, "matches": len(rows), "scope": scope}
    return DataAnswer(
        text, "screen", [screen, widget],
        ConversationContext(intent="screen", ciks=[r.cik for r, _, _ in rows[:MAX_LIST]],
                            label="the companies in the screen"),
        citations=cites,
        how=[{"endpoint": "/v1/facts/screen", "parameters": {"metric": "revenue"},
              "filters": f, "note": "filters applied to each company's latest annual figures"}],
    )  # fmt: skip


def compared_companies(db: Session, text: str) -> list[Company]:
    """The companies a comparison names: "Apple and Microsoft", "AAPL vs MSFT", "Apple, Amazon,
    Netflix". Each part must name a company clearly on its own."""
    from app.services.intel import resolve_company

    found: list[Company] = []
    separators = r"\b(?:and|vs\.?|versus|against|with|to|compare|compared|comparison)\b|,|&|/"
    for part in re.split(separators, text, flags=re.IGNORECASE):
        if len(part.strip()) < 2:
            continue
        c = resolve_company(db, part)
        if c is not None and all(c.cik != f.cik for f in found):
            found.append(c)
    return found[:6]


# ---- helpers -------------------------------------------------------------------------------


def _series(r: MartCompany, metric: str) -> list[dict]:
    """The metric by fiscal year, newest first: {value, period_end, url}. Revenue has its own
    history in the company mart; the other metrics come from the per-year mart (B-01: they
    used to give only the latest year)."""
    if metric == "revenue":
        return loads(r.revenue_history) or []
    db = object_session(r)
    years = []
    if db is not None:
        for y in db.scalars(select(MartCompanyPeriod).where(MartCompanyPeriod.cik == r.cik)
                            .order_by(MartCompanyPeriod.period_end.desc())):  # fmt: skip
            value = getattr(y, metric, None)
            if value is not None:
                url = (loads(y.sources) or {}).get(metric)
                years.append({"value": float(value), "period_end": y.period_end.isoformat(),
                              "url": url, "unit": y.currency or "USD"})  # fmt: skip
    if years:
        return years
    latest = (loads(r.latest_annual) or {}).get(metric)
    return [latest] if latest else []


def _revenue_cell(r: MartCompany) -> dict:
    v = (loads(r.revenue_history) or [None])[0]
    if not v:
        return _cell("no annual report yet" if not r.latest_annual_report_date else "—")
    return _cell(f"{_money(v['value'], v.get('unit'))} (FY ended {v['period_end']})", v.get("url"))


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

    return display_name(r.legal_name, getattr(r, "ticker", None))


def _d(d: date | None) -> str:
    return d.isoformat() if d else "—"


def _money(v: float | None, currency: str | None = "USD") -> str:
    """$1.2 billion for USD; "EUR 36.8 billion" in any other reporting currency (D-04)."""
    if v is None:
        return "—"
    sym = "$" if currency in (None, "USD") else f"{currency} "
    a, s = abs(v), f"\u2212{sym}" if v < 0 else sym  # the minus sign before the currency
    if a >= 1e12:  # JPY, KRW, TWD reporters
        return f"{s}{a / 1e12:,.1f} trillion"
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
