"""C-06: chat intents for today's data, answered from stored data without a model: 13F holders,
segments, the auditor, insider signals, 5% holders (Schedules 13D/G) and the LEI; C-13: pay
versus performance, trading plans, Form 144 notices and what changed in the latest
10-K. Every sentence
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
    # C-13 (2026-11-24): pay versus performance, trading plans, Form 144 notices, 10-K changes
    (
        "pay",
        re.compile(
            r"\b((?:ceo|chief executive|executive|peo|neo)s?'?\s+(?:pay|comp\w*|salar\w*)|"
            r"pay (?:versus|vs\.?|and) (?:performance|tsr)|compensation actually paid|"
            r"executive compensation|say on pay)\b",
            re.I,
        ),
    ),  # fmt: skip
    (
        "trading_plans",
        re.compile(r"\b(10b5-?1|trading (?:plans?|arrangements?)|selling plans?)\b", re.I),
    ),
    (
        "proposed_sales",
        re.compile(
            r"\b(form 144|proposed (?:insider )?sales?|notices? of (?:proposed )?sale)\b", re.I
        ),
    ),  # fmt: skip
    (
        "calendar",
        re.compile(
            r"\b(due|deadlines?|file[sd]? late|late (?:filing|filer|report)|nt 10-?[kq]|"
            r"12b-25|lock-?ups?|quiet period|next (?:10-?[kq]|annual report|quarterly report))\b",
            re.I,
        ),
    ),  # fmt: skip
    (
        "private_raises",
        re.compile(
            r"\b(form d|reg(?:ulation)? d|private (?:placements?|raises?|offerings?))\b", re.I
        ),
    ),  # fmt: skip
    (
        "changes",
        re.compile(
            r"(\brisk factors?\b.*\b(add\w*|new|chang\w*|remov\w*|drop\w*|reword\w*)\b|"
            r"\b(add\w*|new|chang\w*|remov\w*|drop\w*)\b.*\brisk factors?\b|"
            r"what changed in .*\b(10-k|annual report)\b)",
            re.I,
        ),
    ),  # fmt: skip
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
NOT_SIGNALS = "Information, not signals. Not investment advice."  # launch rule: in the text
_BUY = re.compile(r"\b(bought|buy\w*|purchas\w*)\b", re.I)
_SELL = re.compile(r"\b(sold|sell\w*|sales?)\b", re.I)
_LEGAL = {"LLC", "LLP", "LP", "PLC", "NV", "SA", "AG", "SE", "USA", "US", "LTD", "II", "III", "IV",
          "NA", "N.A.", "L.P.", "PC"}  # fmt: skip


_WORDS = {"CO", "INC", "THE", "AND", "OF", "FOR", "NEW", "BAY", "OAK", "SUN", "SKY", "ONE"}


def filed_name(name: str | None) -> str | None:
    """A firm's name as filed, readable: an all-caps name is title-cased word by word, keeping
    legal forms, short acronyms (UBS), words without vowels (KPMG) and "&"; a name with any
    lower-case letter is left exactly as filed. Words are never joined or split."""
    if not name or any(ch.islower() for ch in name):
        return name
    out = []
    for w in name.split():
        core = w.strip(",.")
        word = core not in _WORDS  # short common words are words, not acronyms
        acronym = word and (len(core) <= 3 or not any(v in core for v in "AEIOUY"))
        keep = core in _LEGAL or acronym or not core[:1].isalpha()
        out.append(w if keep else w.capitalize())
    return " ".join(out)


_KEEP_IN_PERSON = {"JR", "SR", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
_ENTITY_WORDS = (_LEGAL - _KEEP_IN_PERSON) | {"INC", "CO", "CORP", "TRUST", "FUND", "LIMITED",
                                               "HOLDINGS", "PARTNERS", "CAPITAL", "&"}  # fmt: skip


def _cap(word: str) -> str:
    """LEVINSON -> Levinson, O'BRIEN -> O'Brien, SMITH-JONES -> Smith-Jones."""
    return re.sub(r"[A-Z]+", lambda m: m.group(0).capitalize(), word)


def filed_owner_name(name: str | None) -> str | None:
    """A Form 4 owner's name as filed, readable, in filed order (never reordered: filers put the
    surname first or last, and reordering would be a guess). An all-caps person's name is cased
    word by word; initials, JR/SR and roman numerals stay as filed. An owner whose name carries
    a legal form (a fund, a firm) follows filed_name. A name with any lower-case letter is left
    exactly as filed."""
    if not name or any(ch.islower() for ch in name):
        return name
    words = name.split()
    if any(w.strip(",.") in _ENTITY_WORDS for w in words):
        return filed_name(name)
    out = []
    for w in words:
        core = w.strip(",.")
        keep = len(core) <= 1 or core in _KEEP_IN_PERSON or not core[:1].isalpha()
        out.append(w if keep else _cap(w))
    return " ".join(out)


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
        who = filed_name(h["name"])
        n = _cite(b, f"13F of {who}, filed {h['filing_date']}", url)
        parts.append(f"{who} ({money(h['value_usd'], 'USD')}) [{n}]")
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
    text = (f"{_name(b)}'s auditor is {filed_name(cur['name'])}{where}, as named in its "
            f"{rep['form_type']}"
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


def _trades(db: Session, b: Brief, code: str, since: date, ref: date) -> list[tuple]:
    """Open-market purchases (P) or sales (S) on Forms 4, per filing: (filing, date, shares,
    average price)."""
    from app.db.models import InsiderFiling, InsiderTransaction

    rows = db.execute(
        select(InsiderTransaction.accession_number, InsiderTransaction.trans_date,
               InsiderTransaction.shares, InsiderTransaction.price)
        .where(InsiderTransaction.issuer_cik == b.company.cik,
               InsiderTransaction.row_kind == "transaction",
               InsiderTransaction.is_derivative.is_(False),
               InsiderTransaction.trans_code == code,
               InsiderTransaction.trans_date >= since, InsiderTransaction.trans_date <= ref)
    ).all()  # fmt: skip
    per: dict[str, list] = {}
    for acc, d, shares, price in rows:
        per.setdefault(acc, []).append((d, float(shares or 0), float(price or 0)))
    filings = {f.accession_number: f for f in db.scalars(
        select(InsiderFiling).where(InsiderFiling.accession_number.in_(list(per)),
                                    InsiderFiling.issuer_cik == b.company.cik))}  # fmt: skip
    out = []
    for acc, items in per.items():
        f = filings.get(acc)
        if f is None:
            continue
        shares = sum(x[1] for x in items)
        value = sum(x[1] * x[2] for x in items)
        out.append((f, max(x[0] for x in items), shares, value / shares if shares else None))
    return sorted(out, key=lambda t: t[1], reverse=True)


def insiders(db: Session, b: Brief, as_of: date | None, text: str = "") -> str:
    from app.services import insider_activity
    from app.services.sec_client import filing_index_url

    ref = as_of or date.today()
    since = ref - timedelta(days=INSIDER_DAYS)
    wants = "P" if _BUY.search(text) else "S" if _SELL.search(text) else None
    if wants:  # a buy question answers purchases only, a sell question sales only
        what = "purchases" if wants == "P" else "sales"
        trades = _trades(db, b, wants, since, ref)[:5]
        if not trades:
            return (f"No open-market {what} by {_name(b)} insiders in the Forms 4 loaded here "
                    f"for the last year. {NOT_SIGNALS}")  # fmt: skip
        verb = "bought" if wants == "P" else "sold"
        parts = []
        for f, d, shares, price in trades:
            n = _cite(b, f"Form 4 filed {f.filing_date}",
                      filing_index_url(b.company.cik, f.accession_number))  # fmt: skip
            role = f.officer_title or ("director" if f.is_director else None)
            who = f"{filed_owner_name(f.owner_name)}" + (f" ({role})" if role else "")
            at = f" at an average ${price:,.2f}" if price else ""
            parts.append(f"{who} {verb} {shares:,.0f} shares{at} on {d} [{n}]")
        return (f"Open-market {what} by {_name(b)} insiders in the last year (Forms 4): "
                + "; ".join(parts) + f". {NOT_SIGNALS}")  # fmt: skip
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


METHODS = {  # plain words, as the company page says them
    "sec": "reported by the company to the SEC",
    "override": "checked by hand against GLEIF and the SEC record",
    "gleif_name_jurisdiction": "matched by name and jurisdiction",
    "name_jurisdiction": "matched by name and jurisdiction",
    "gleif_name_us_state_differs": "matched by name and city",
    "gleif_name_us_country": "matched by name and country",
}


def lei(db: Session, b: Brief, as_of: date | None) -> str:
    from app.services import identity

    block = identity.for_company(db, b.company.cik)
    if not block or not block.get("lei"):
        return f"No LEI is linked to {_name(b)} in the data loaded here."
    # only sec.gov/Archives filings are ever linked: GLEIF is named, not linked (PM, 2026-11-23)
    n = b.cite(f"GLEIF public record, LEI {block['lei']}, CC0 golden copy", None)
    how = METHODS.get(block["match_method"], "matched by name")
    holder = f" ({block['lei_name']})" if block.get("lei_name") else ""
    return f"{_name(b)}'s LEI is {block['lei']}{holder}, {how} [{n}]."


_FISCAL_YEAR = re.compile(r"\b(?:fiscal(?:\s+year)?(?:\s+ended)?|fy)\s*'?((?:19|20)\d{2})\b", re.I)
_FILED_DATE = re.compile(
    r"\b(?:filed|proxy|dated)\s+(?:on\s+)?\d{4}-\d{2}-\d{2}\b|\d{10}-\d{2}-\d{6}", re.I
)
_BARE_YEAR = re.compile(r"(?<![\d-])((?:19|20)\d{2})(?![\d-])")


def asked_fiscal_year(text: str) -> int | None:
    """The fiscal year a pay question names ("fiscal 2024", "FY2024", "in 2023", "fiscal year
    ended 2024-09-28"); never a filing date ("proxy filed 2026-01-08") or an accession number."""
    m = _FISCAL_YEAR.search(text)
    if m:
        return int(m.group(1))
    m = _BARE_YEAR.search(_FILED_DATE.sub(" ", text))
    return int(m.group(1)) if m else None


def pay(db: Session, b: Brief, as_of: date | None, text: str = "") -> str:
    """C-13: the proxy's pay-versus-performance table (D-10), as disclosed; the fiscal year asked
    about, or says it is not in the table (never another year in its place)."""
    from app.services import executive_pay

    block = executive_pay.for_company(db, b.company.cik, as_of)
    if not block["years"]:
        return (f"No pay-versus-performance table is tagged in the proxies loaded here for "
                f"{_name(b)}.")  # fmt: skip
    cur = block["currency"] or "USD"

    def amt(v) -> str:
        return money(v, cur) if v is not None else "not given"

    asked = asked_fiscal_year(text)
    at = 0
    if asked is not None:
        # the year as tagged: a 52-53 week year ending 2025-01-03 is tagged 2024-12-31, the
        # fiscal 2024 the company names
        tagged = [executive_pay.month_end(date.fromisoformat(x["fiscal_year_end"])).year
                  if x["fiscal_year_end"] else None for x in block["years"]]  # fmt: skip
        at = tagged.index(asked) if asked in tagged else -1
        if at < 0:
            have = ", ".join(x["fiscal_year_end"] for x in block["years"] if x["fiscal_year_end"])
            return (f"Fiscal {asked} is not in the pay-versus-performance tables tagged in "
                    f"{_name(b)}'s proxies loaded here; they cover the fiscal years ended "
                    f"{have}. {NOT_SIGNALS}")  # fmt: skip
    y = block["years"][at]
    src = y["source"]
    n = _cite(b, f"{src['form']} filed {src['filed_date']}", src["source_url"])
    peo = "; ".join(f"{p['name'] or 'the PEO'}: {amt(p['total_comp'])} total (Summary "
                    f"Compensation Table), {amt(p['comp_actually_paid'])} compensation actually "
                    "paid" for p in y["peo"])  # fmt: skip
    ended = y["fiscal_year_end"] + (
        " (month end; the exact date is not in the annual reports loaded here)"
        if y.get("fiscal_year_end_rounded")
        else ""
    )
    text = (f"For the fiscal year ended {ended}, {_name(b)}'s proxy filed "
            f"{src['filed_date']} reports {peo} [{n}].")  # fmt: skip
    neo = y["neo_average"]
    if neo["total_comp"] is not None:
        text += (
            f" The other named executives averaged {amt(neo['total_comp'])} total and "
            f"{amt(neo['comp_actually_paid'])} compensation actually paid [{n}]."
        )
    if y["tsr"] is not None:
        peer = ""
        if y["peer_tsr"] is not None:
            peer = f", against {y['peer_tsr']:g} for the peer group"
        text += f" Total shareholder return: $100 invested became {y['tsr']:g}{peer} [{n}]."
    earlier = [x for x in block["years"][at + 1 : at + 4]
               if x["peo"] and x["peo"][0]["comp_actually_paid"] is not None
               and x["tsr"] is not None]  # fmt: skip
    if earlier:
        trend = "; ".join(f"FY ended {x['fiscal_year_end']}: "
                          f"{amt(x['peo'][0]['comp_actually_paid'])} vs TSR {x['tsr']:g}"
                          for x in earlier)  # fmt: skip
        text += f" Earlier years, PEO compensation actually paid vs TSR: {trend} [{n}]."
    return text + f" As disclosed in the proxy. {NOT_SIGNALS}"


def trading_plans(db: Session, b: Brief, as_of: date | None) -> str:
    """C-13: Rule 10b5-1 and other trading plans, Item 408(a) (D-11)."""
    from app.services import insider_plans

    ref = as_of or date.today()
    rows = insider_plans.plans(db, b.company.cik, ref.replace(year=ref.year - 2), as_of, 8)
    if not rows:
        return (f"No trading-plan adoptions or terminations are tagged in {_name(b)}'s 10-Q and "
                f"10-K filings loaded here for the last two years. {NOT_SIGNALS}")  # fmt: skip
    parts = []
    for r in rows:
        f = r["filing"]
        n = _cite(b, f"{f['form']} filed {f['filed_date']}", f["source_url"])
        kind = {
            "rule_10b5_1": "a Rule 10b5-1 plan",
            "non_rule_10b5_1": "a non-Rule 10b5-1 arrangement",
        }.get(r["plan_type"], "a plan")
        when = r["date"] or r["date_as_written"] or "on a date not given"
        who = r["person_name"] or "an officer or director"
        title = f" ({r['title']})" if r["title"] else ""
        extra = f" covering up to {r['shares']:,.0f} shares" if r["shares"] else ""
        parts.append(f"{who}{title} {r['action']} {kind} on {when}{extra} ({f['form']} filed "
                     f"{f['filed_date']}) [{n}]")  # fmt: skip
    return (f"Trading plans at {_name(b)}, as tagged in its 10-Q and 10-K filings: "
            + "; ".join(parts) + f". {NOT_SIGNALS}")  # fmt: skip


def proposed_sales(db: Session, b: Brief, as_of: date | None) -> str:
    """C-13: Form 144 notices and the Form 4 that followed (D-12)."""
    from app.services import form144

    ref = as_of or date.today()
    rows = form144.for_company(db, b.company.cik, ref - timedelta(days=365), as_of, 6)
    if not rows:
        return (f"No Form 144 notices of proposed sale for {_name(b)} in the last 12 months are "
                f"loaded here. {NOT_SIGNALS}")  # fmt: skip
    parts = []
    for r in rows:
        f = r["filing"]
        n = _cite(b, f"Form 144 filed {f['filed_date']}", f["source_url"])
        who = filed_owner_name(r["person_name"]) or "an insider"
        value = (f", about {money(r['aggregate_market_value'], 'USD')} by the filer's estimate"
                 if r["aggregate_market_value"] else "")  # fmt: skip
        part = (f"{who} filed a notice on {f['filed_date']} to sell {r['shares']:,.0f} shares"
                f"{value} [{n}]")  # fmt: skip
        fb = r["followed_by"]
        if fb:
            m = _cite(b, f"Form 4 filed {fb['filed_date']}", fb["source_url"])
            part += (f", and a Form 4 filed {fb['filed_date']} reports a sale of "
                     f"{fb['shares']:,.0f} shares on {fb['transaction_date']} [{m}]")  # fmt: skip
        parts.append(part)
    return (f"Form 144 notices for {_name(b)}: " + "; ".join(parts) + ". A notice does not "
            f"oblige a sale. {NOT_SIGNALS}")  # fmt: skip


def changes(db: Session, b: Brief, as_of: date | None) -> str:
    """C-13: risk factors added, removed and reworded against the previous 10-K (X-14)."""
    from app.services import tenk_sections

    latest = tenk_sections.annual_reports(db, b.company.cik, as_of, limit=1)
    if not latest:
        return f"No 10-K annual report for {_name(b)} is loaded here."
    try:
        d = tenk_sections.changes(db, latest[0])
    except tenk_sections.NotAvailable as exc:
        return f"{exc.message} ({_name(b)}, 10-K filed {latest[0].filing_date})."
    f, p = d["filing"], d["prior"]
    n = _cite(b, f"10-K filed {f['filed_date']}", f["source_url"])
    rf = d["risk_factors"]
    if p is None:
        return (f"{_name(b)}'s 10-K filed {f['filed_date']} lists {rf['counts']['now']} risk "
                f"factors [{n}]; no earlier 10-K is loaded to compare with.")  # fmt: skip
    m = _cite(b, f"10-K filed {p['filed_date']}", p["source_url"])
    c = rf["counts"]
    text = (f"{_name(b)}'s 10-K filed {f['filed_date']} [{n}], compared with the one filed "
            f"{p['filed_date']} [{m}]: {_count(c['added'], 'risk factor')} added, "
            f"{c['removed']} removed, {c['reworded']} reworded and {c['unchanged']} "
            "unchanged.")  # fmt: skip
    if rf["added"]:
        text += " Added: " + "; ".join(_quote(h["heading"]) for h in rf["added"][:4]) + f" [{n}]."
    if rf["removed"]:
        text += (" Removed: " + "; ".join(_quote(h["heading"]) for h in rf["removed"][:4])
                 + f" [{m}].")  # fmt: skip
    return text


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _quote(heading: str, limit: int = 160) -> str:
    """A heading in quotes, cut at a word boundary when it is long."""
    h = heading if len(heading) <= limit else heading[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return f"\u201c{h}\u201d"


def calendar(db: Session, b: Brief, as_of: date | None, text: str = "") -> str:
    """C-13: the next filing deadline (derived, with its rule), how the last ones were met, late
    notices and IPO dates, from the company calendar (X-15)."""
    from app.services import company_calendar as cal

    ref = as_of or date.today()
    items = cal.for_company(db, b.company, ref - timedelta(days=730), ref + timedelta(days=400),
                            cal.KINDS, today=ref)  # fmt: skip
    name = _name(b)
    deadlines = [i for i in items if i["kind"] == "filing_deadline"]
    asked = re.search(r"\b(10-?k|10-?q|20-?f)\b", text, re.I)
    form = asked.group(1).upper().replace("-", "").replace("10K", "10-K").replace(
        "10Q", "10-Q").replace("20F", "20-F") if asked else None  # fmt: skip
    # the next deadline not met yet (of the form asked about, if one is), and the reports
    # already filed against their deadlines
    open_ = [i for i in deadlines if not i.get("met_by") and i["date"] >= ref.isoformat()]
    nxt = next((i for i in open_ if not form or i["title"].startswith(form)), None) or (
        open_[0] if open_ else None
    )
    past = [i for i in deadlines if i.get("met_by") and (not form or i["title"].startswith(form))]
    parts = []
    # a deadline the question names by its due date or period end ("10-K due (period ending
    # 2026-09-26) (2026-11-25)"): that one, met or not, never the next one in its place
    days = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text))
    hit = next((i for i in deadlines if (i["date"] in days or i.get("period_end") in days)
                and (not form or i["title"].startswith(form))), None)  # fmt: skip
    if hit:
        kind = hit["title"].split(" due")[0]
        n = _cite(b, f"{hit['source']['form']} filed {hit['source']['filed_date']}",
                  hit["source"]["source_url"])  # fmt: skip
        rule = f"derived: {hit['basis']}; from the filer category and the report periods"
        if hit.get("met_by"):
            m = _cite(b, f"{hit['met_by']['form']} filed {hit['met_by']['filed_date']}",
                      hit["met_by"]["source_url"])  # fmt: skip
            how = "after" if hit.get("filed_late") else "by"
            parts.append(f"{name}'s {kind} for the period ending {hit['period_end']} was due "
                         f"{hit['date']} ({rule}) [{n}]. It was filed "
                         f"{hit['met_by']['filed_date']}, {how} the due date [{m}].")  # fmt: skip
        else:
            parts.append(f"{name}'s {kind} for the period ending {hit['period_end']} is due "
                         f"{hit['date']} ({rule}) [{n}]; it has not been filed yet.")  # fmt: skip
        nxt, past = None, []
    if nxt:
        n = _cite(b, f"{nxt['source']['form']} filed {nxt['source']['filed_date']}",
                  nxt["source"]["source_url"])  # fmt: skip
        parts.append(f"{name}'s next {nxt['title'].split(' due')[0]} is due {nxt['date']} for "
                     f"the period ending {nxt['period_end']} (derived: {nxt['basis']}; from the "
                     f"filer category and the report periods) [{n}].")  # fmt: skip
    elif not deadlines:
        parts.append(f"No filing deadline can be worked out for {name}: the SEC's record does "
                     "not say its filer category, or no periodic report is loaded.")  # fmt: skip
    if past:
        last = past[-1]
        if last.get("met_by"):
            m = _cite(b, f"{last['met_by']['form']} filed {last['met_by']['filed_date']}",
                      last["met_by"]["source_url"])  # fmt: skip
            how = "after" if last.get("filed_late") else "by"
            parts.append(f"The last one, for the period ending {last['period_end']}, was due "
                         f"{last['date']} and filed {last['met_by']['filed_date']}, {how} the due "
                         f"date [{m}].")  # fmt: skip
        late = [i for i in past if i.get("filed_late")]
        if late:
            refs = []
            for i in late[-4:]:
                k = _cite(b, f"{i['met_by']['form']} filed {i['met_by']['filed_date']}",
                          i["met_by"]["source_url"])  # fmt: skip
                refs.append(f"{i['period_end']} (due {i['date']}, filed "
                            f"{i['met_by']['filed_date']}) [{k}]")  # fmt: skip
            parts.append("Filed after the derived due date in the last two years: "
                         + "; ".join(refs) + ".")  # fmt: skip
        elif re.search(r"\blate\b", text, re.I):
            parts.append("In the last two years every report shown was filed by its derived "
                         "due date.")  # fmt: skip
    notices = [i for i in items if i["kind"] == "late_notice" and i["date"] <= ref.isoformat()]
    if notices:
        refs = []
        for i in notices[-3:]:
            k = _cite(b, f"{i['source']['form']} filed {i['date']}", i["source"]["source_url"])
            refs.append(f"{i['source']['form']} on {i['date']} [{k}]")
        parts.append("Notices of late filing (Rule 12b-25): " + "; ".join(refs) + ".")
    elif re.search(r"\blate\b|12b-25|\bnt\b", text, re.I):
        parts.append("No notice of late filing (NT 10-K or NT 10-Q) in the last two years.")
    for i in items:
        if i["kind"] in ("lockup_expiry", "quiet_period_end") and i["date"] >= ref.isoformat():
            k = _cite(b, f"424B4 filed {i['source']['filed_date']}", i["source"]["source_url"])
            parts.append(f"{i['title']} on {i['date']} (derived: {i['basis']}) [{k}].")
    return " ".join(parts) or f"No dated items for {name} in the data loaded here."


def private_raises(db: Session, b: Brief, as_of: date | None, text: str = "") -> str:
    """D-15: one issuer's Form D offerings (an Ask link from the Explorer), cited; the one
    offering a quoted accession number names, when the question quotes one."""
    from app.services import form_d

    asked, one = form_d.offering_for(db, text)
    if one is not None:
        return form_d.describe(one, lambda lbl, url: _cite(b, lbl, url), money, asked)
    items, _ = form_d.search(db, cik=b.company.cik, limit=5,
                             end=as_of)  # fmt: skip
    name = _name(b)
    through = form_d.covered_through(db)
    missing = (f"No Form D with accession number {asked} is in the Form D data sets loaded "
               "here. " if asked else "")  # fmt: skip
    if not items:
        return (
            f"{missing}No Form D notice by {name} is in the Form D data sets loaded here"
            + (f" (through {through.isoformat()})" if through else "")
            + "."
        )
    parts = []
    for i in items:
        lf = i["latest_filing"]
        n = _cite(b, f"Form {lf['form']} filed {lf['filed_date']}", lf["source_url"])
        sold = money(i["total_amount_sold"], "USD") if i["total_amount_sold"] is not None \
            else "not given"  # fmt: skip
        size = (money(i["total_offering_amount"], "USD") if i["total_offering_amount"]
                is not None else "indefinite")  # fmt: skip
        parts.append(f"Form {lf['form']} filed {lf['filed_date']}: {sold} sold (offering size "
                     f"{size}; {i['industry_group'] or 'industry not given'}) [{n}]")  # fmt: skip
    return f"{missing}Form D offerings by {name}: " + "; ".join(parts) + ". " + form_d.BASIS


HOW = {  # the endpoint that returns the same data (C-01 "how I got this")
    "holders": "ownership", "five_percent": "holders", "auditor": "overview",
    "segments": "segments", "insiders": "insider-transactions", "lei": "overview",
    "pay": "executive-pay", "trading_plans": "insider-plans", "proposed_sales": "insider-plans",
    "changes": "changes", "calendar": "calendar", "private_raises": "private-raises",
}  # fmt: skip

ANSWERS = {"holders": holders, "five_percent": five_percent, "auditor": auditor,
           "segments": segments, "insiders": insiders, "lei": lei, "pay": pay,
           "trading_plans": trading_plans, "proposed_sales": proposed_sales,
           "changes": changes, "calendar": calendar,
           "private_raises": private_raises}  # fmt: skip


def answer(db: Session, b: Brief, intent: str, as_of: date | None, text: str = "") -> str:
    if intent == "insiders":
        return insiders(db, b, as_of, text)
    if intent == "calendar":
        return calendar(db, b, as_of, text)
    if intent == "private_raises":
        return private_raises(db, b, as_of, text)
    if intent == "pay":
        return pay(db, b, as_of, text)
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
