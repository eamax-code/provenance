"""Company intelligence brief: a deterministic, cited summary that the chat model phrases.

Every number and claim in the brief comes from stored SEC data and carries a citation number
pointing at the SEC record. The language model sees only this context (see routes_chat).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, FinancialFact
from app.services import officer_changes
from app.services.company_lookup import (
    core_name,
    fuzzy_companies,
    normalize_name,
    search_companies,
)
from app.services.form8k import ITEM_TITLES, LEADERSHIP_ITEM, split_items
from app.services.point_in_time import known_by
from app.services.sec_client import company_filings_url

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
    "last", "past", "previous", "year", "years", "fiscal", "over", "recent", "trend", "chart",
    "history", "sales", "profit", "profits", "earnings", "income", "net", "operating", "cash",
    "flow", "assets", "total", "grow", "growing", "grew", "much", "many", "since", "with",
    "at", "to", "by", "from", "any", "change", "changes", "changed", "quickly",
    # Conversation words that begin company names ("you" -> Youdao, "more" -> Moregain).
    "you", "your", "we", "our", "us", "i", "it", "they", "them", "this", "that", "these", "those",
    "other", "others", "else", "more", "most", "some", "all", "information", "info", "data",
    "details", "detail", "insight", "insights", "share", "shared", "can", "could", "would",
    "should", "will", "be", "been", "there", "here", "also", "please", "know", "explain",
    "summary", "summarise", "summarize", "overview", "news", "update", "updates", "why", "when",
    "where", "which", "same", "next", "then", "now", "like", "compare", "versus", "vs",
    # Going public and what a prospectus covers ("main" -> Main Street, "grown" -> Grown Rogue).
    "main", "key", "top", "biggest", "major", "grown", "risk", "risks", "ipo", "offering",
    "public", "raise", "raising", "raised", "money", "proceeds", "plans", "plan", "spend",
    "owns", "owner", "owners", "stake", "investors", "valuation", "listing", "prospectus",
    # Forecast questions ("Outlook", "Forecast" and "Predictive" begin company names).
    "forecast", "forecasts", "forecasting", "predict", "prediction", "predictions",
    "projection", "projections", "project", "outlook", "estimate", "estimates", "coming",
    "following", "upcoming", "future",
    # Time words ("today" -> USA Today, "as" -> Asure).
    "as", "today", "tomorrow", "yesterday", "currently", "current", "right",
}  # fmt: skip
# Acronyms in questions that are also tickers ("AI" is C3.ai, "IT" is Gartner).
_ACRONYMS = {
    "AI", "CEO", "CFO", "COO", "CTO", "IPO", "SEC", "US", "USA", "EPS", "ESG", "FY", "GAAP",
    "SPAC", "ETF", "YOY", "TTM", "CAGR", "EBITDA", "FCF", "ROI", "ROE", "IT", "HR", "PR",
}  # fmt: skip
_LEADERSHIP_Q = re.compile(
    r"\b(leadership|ceo|cfo|coo|cto|chief|executives?|officers?|directors?|board|management|"
    r"resign\w*|appoint\w*|hired?|depart\w*|succession|successor|step(?:s|ped)? down|chair\w*)\b",
    re.IGNORECASE,
)
_PAY_Q = re.compile(
    r"\b(pay|paid|compensation|salary|salaries|bonus|stock awards?)\b", re.IGNORECASE
)
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}
LEADERSHIP_YEARS = 3
STALE_DAYS = 120


@dataclass
class Brief:
    company: Company
    as_of: date | None
    metrics: list[dict] = field(default_factory=list)
    filings: list[dict] = field(default_factory=list)
    leadership_filings: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)

    def cite(self, label: str, url: str) -> int:
        self.citations.append({"n": len(self.citations) + 1, "label": label, "url": url})
        return len(self.citations)

    def context(self) -> str:
        return "\n".join(self.context_lines)


def resolve_company(db: Session, text: str, *, follow_up: bool = False) -> Company | None:
    """Find the company a free-text question is about: ticker or CIK first, then names.

    In a follow-up (a company is already under discussion) only a clearly named company
    switches it: a ticker in capitals, a whole name, or a capitalised start of a name."""
    text = re.sub(r"['\u2019]s\b", "", text)  # "Apple's" -> "Apple"
    words = [w.rstrip(".") for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.&-]*", text)]
    for prev, w in zip(["", *words], words, strict=False):
        # Short numbers are counts ("last 5 years"), not CIKs, unless the user says "CIK".
        cik_like = w.isdigit() and len(w) <= 10 and (len(w) >= 5 or prev.lower() == "cik")
        if cik_like or (w.isupper() and 1 <= len(w) <= 6 and w not in _ACRONYMS):
            hits, _ = search_companies(db, w, limit=1)
            if hits and hits[0].match_type in ("cik", "ticker"):
                return hits[0].company
    useful = [w for w in words if w.lower() not in _STOP]
    # Words as typed first; only then without a trailing "s" ("apples growth" means Apple), so
    # "changes at Netflix" finds Netflix before "Change" finds another company.
    for singular in (False, True):
        for size in (3, 2, 1):
            found = []
            for i in range(len(useful) - size + 1):
                phrase = " ".join(useful[i : i + size])
                if singular:
                    if len(phrase) <= 4 or phrase[-1] not in "sS" or phrase[-2] in "sS":
                        continue
                    phrase = phrase[:-1]
                if len(phrase) < 3:
                    continue
                hits, _ = search_companies(db, phrase, limit=50)
                found += [
                    (h, phrase)
                    for h in hits
                    if h.match_type in _MATCH_RANK
                    and _names_it(h, phrase)
                    and (not follow_up or _named(h, phrase))
                ]
            if found:
                # "How fast is Tesla growing": Tesla is a whole name, "fast" only starts Fastenal;
                # "the main risks for Anthropic": a named company beats a word that is a ticker.
                best, _ = max(found, key=lambda x: (_named(*x), _match_rank(*x), _name_score(*x)))
                return best.company
    # A typo ("Mircosoft", "amazn"): the nearest name within one or two letters.
    best = None
    for size in (2, 1):
        for i in range(len(useful) - size + 1):
            phrase = " ".join(useful[i : i + size])
            lower_word = size == 1 and phrase.islower()
            if follow_up and not phrase[:1].isupper():
                continue
            for dist, c in fuzzy_companies(db, phrase, limit=1, whole_name=lower_word):
                rank = (dist, not c.ticker)
                if dist > 0 and (best is None or rank < (best[0], not best[1].ticker)):
                    best = (dist, c)
        if best:
            return best[1]
    return None


def _names_it(hit, phrase: str) -> bool:
    """A name match counts only when it ends on a word boundary ("active" does not name
    ActiveCare), and a single lower-case word must be the whole name ("apple" is Apple Inc.,
    "active" is not Active Network Inc.); tickers and exact names always count."""
    if hit.match_type == "former_name":
        # "Facebook" names Meta Platforms; "book" or a common word inside an old name does not.
        core = core_name(hit.former_name or "")
        return core == phrase.lower() or (
            phrase[:1].isupper() and core.startswith(phrase.lower() + " ")
        )
    if hit.match_type not in ("name_prefix", "name_exact"):
        return True
    if hit.match_type == "name_exact":
        return True
    name, typed = normalize_name(hit.company.legal_name), phrase.lower()
    if len(name) > len(typed) and name[len(typed)].isalnum():
        return False
    if " " not in phrase and phrase.islower():
        return core_name(hit.company.legal_name) == typed
    return True


def candidate_companies(db: Session, text: str, limit: int = 5) -> list[Company]:
    """Companies a question might mean when none is clear: name starts and near spellings of its
    words, listed companies first. Offered as choices, never picked."""
    words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9.&-]*", text) if w.lower() not in _STOP]
    seen: dict[str, tuple] = {}
    for w in words:
        if len(w) < 3:
            continue
        hits, _ = search_companies(db, w, limit=limit)
        ranked = [(0.0, h.company) for h in hits] or fuzzy_companies(db, w, limit=limit)
        for dist, c in ranked:
            key = (dist, not c.ticker, len(c.legal_name))
            if c.cik not in seen or key < seen[c.cik][0]:
                seen[c.cik] = (key, c)
    return [c for _, c in sorted(seen.values(), key=lambda x: x[0])[:limit]]


_COVERAGE_Q = re.compile(
    r"\bhow many\b.{0,40}\b(compan(?:y|ies)|publics?|filers?|issuers?|tickers?|filings|facts)\b"
    r"|\b(?:what|which) compan(?:y|ies) (?:do|does|can) (?:you|this|it)\b"
    r"|\b(?:your|the|this service'?s?) coverage\b|\bwhat (?:data|companies) do you have\b",
    re.IGNORECASE,
)


def is_coverage_question(text: str) -> bool:
    """Questions about this service's data rather than one company."""
    return bool(_COVERAGE_Q.search(text))


_MATCH_RANK = {"ticker": 3, "name_exact": 2, "name_prefix": 1, "former_name": 1}


def _named(hit, phrase: str) -> bool:
    """Whether the phrase clearly names this company rather than merely starting its name."""
    if hit.match_type == "ticker":
        return phrase.isupper()
    if hit.match_type == "former_name":
        return _core_name(hit.former_name or "") == _core_name(phrase) or phrase[:1].isupper()
    if hit.match_type == "name_exact" or _core_name(hit.company.legal_name) == _core_name(phrase):
        return True
    return phrase[:1].isupper()


def _match_rank(hit, phrase: str) -> int:
    # A lower-case word that happens to be a ticker ("fast" is FAST) is no stronger than a prefix.
    if hit.match_type == "ticker" and not phrase.isupper():
        return 1
    return _MATCH_RANK[hit.match_type]


_core_name = core_name


def _name_score(hit, phrase: str) -> tuple:
    """ "Apple" means Apple Inc., not Apple REIT Six; "Hawaiian Electric" the listed parent."""
    c = hit.company
    return (bool(c.ticker), _core_name(c.legal_name) == _core_name(phrase), -len(c.legal_name))


_KEEP_UPPER = {"LLC", "PLC", "LP", "NV", "SA", "AG", "SE", "USA", "US", "II", "III", "IV"}


def display_name(legal_name: str) -> str:
    """ "COSTCO WHOLESALE CORP /NEW" reads as "Costco Wholesale Corp" in an answer."""
    name = re.sub(r"\s*/[A-Z]{1,5}/?\s*$", "", legal_name).strip()
    if name != name.upper():
        return name
    words: list[str] = []
    for w in name.split():
        if w == "COM" and words:  # the SEC drops the dot: "AMAZON COM INC" is Amazon.com
            words[-1] += ".com"
            continue
        words.append(w if w in _KEEP_UPPER or not w[:1].isalpha() else w.capitalize())
    return " ".join(words)


def money(v: Decimal | float) -> str:
    x = float(v)
    for div, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if abs(x) >= div:
            return f"${x / div:,.1f} {word}"
    return f"${x:,.0f}"


def annual_series(db: Session, cik: str, metric: str, as_of: date | None) -> list[FinancialFact]:
    """One reported annual figure per fiscal year, newest first."""
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

    def rank(f: FinancialFact) -> tuple:
        # An annual report beats a proxy's pay-versus-performance table for the same year.
        return (f.form_type in ANNUAL_FORMS, f.filed_date or date.min, f.accession_number or "")

    latest: dict[date, FinancialFact] = {}
    for f in db.scalars(stmt):
        cur = latest.get(f.period_end)
        if cur is None or rank(f) > rank(cur):
            latest[f.period_end] = f
    return [latest[k] for k in sorted(latest, reverse=True)]


def build_brief(db: Session, company: Company, as_of: date | None = None) -> Brief:
    b = Brief(company=company, as_of=as_of)
    n = b.cite("SEC EDGAR filing list", company_filings_url(company.cik))
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
    b.coverage = _coverage(db, company.cik, as_of)
    cov = b.coverage
    if cov["filings"]:
        b.context_lines.append(
            f"[{n}] Filings loaded in this service for the company: {cov['filings']}, filed "
            f"{cov['first_filed']} to {cov['last_filed']}; 8-K filings since {cov['since']}: "
            f"{cov['eight_ks_since']}. Anything filed after {cov['last_filed']} is not loaded."
        )
    else:
        b.context_lines.append(f"[{n}] No filings are loaded in this service for the company.")

    for metric, label in METRIC_LABELS.items():
        series = annual_series(db, company.cik, metric, as_of)
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
                "display": money(cur.value),
                "prior_period_end": prev.period_end.isoformat() if prev else None,
                "prior_value": float(prev.value) if prev else None,
                "prior_display": money(prev.value) if prev else None,
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
        line = f"[{n}] {label}, fiscal year ended {cur.period_end}: {money(cur.value)}"
        if prev is not None:
            line += f"; prior year (ended {prev.period_end}) {money(prev.value)}"
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

    since = date.fromisoformat(cov["since"])
    leadership = leadership_filings(db, company.cik, as_of)
    b.coverage["leadership_since"] = db.scalar(
        select(func.count()).select_from(
            stmt.where(Filing.items.like(f"%{LEADERSHIP_ITEM}%"), Filing.filing_date >= since)
            .with_only_columns(Filing.id)
            .subquery()
        )
    )
    readings = officer_changes.changes_by_accession(db, [f.accession_number for f in leadership])
    for f in leadership:
        n = b.cite(f"8-K item 5.02 filed {f.filing_date}", f.source_url)
        card = _filing_card(f, split_items(f.items), n)
        reading = readings.get(f.accession_number)
        card["reading"] = reading["status"] if reading else "not_read"
        card["changes"] = [
            officer_changes.change_dict(c) for c in (reading or {}).get("changes", [])
        ]
        b.leadership_filings.append(card)
        if card["changes"]:
            for c in reading["changes"]:
                flag = "" if c.verified else " (details not confirmed against the filing text)"
                b.context_lines.append(
                    f"[{n}] Leadership change in 8-K filed {f.filing_date} (item 5.02): "
                    f"{officer_changes.describe(c)}{flag}"
                )
        else:
            b.context_lines.append(
                f"[{n}] Leadership filing: 8-K filed {f.filing_date} under item 5.02 "
                "(directors or officers). "
                + (
                    "It names no individual director or officer change."
                    if card["reading"] == "ok"
                    else "Its text has not been read here."
                )
            )
    return b


def leadership_filings(db: Session, cik: str, as_of: date | None, limit: int = 5) -> list[Filing]:
    """The latest 8-Ks with item 5.02 within the leadership window."""
    ref = as_of or date.today()
    stmt = select(Filing).where(
        Filing.cik == cik,
        Filing.items.like(f"%{LEADERSHIP_ITEM}%"),
        Filing.filing_date >= ref - timedelta(days=LEADERSHIP_YEARS * 365),
    )
    if as_of:
        stmt = stmt.where(Filing.filing_date <= as_of)
    rows = db.scalars(
        stmt.order_by(Filing.filing_date.desc(), Filing.accession_number.desc()).limit(limit)
    )
    return [f for f in rows if LEADERSHIP_ITEM in split_items(f.items)]


def _coverage(db: Session, cik: str, as_of: date | None) -> dict:
    """How much of the company's filing history is loaded, so answers can say what they cover."""
    ref = as_of or date.today()
    since = ref - timedelta(days=LEADERSHIP_YEARS * 365)
    base = select(Filing).where(Filing.cik == cik)
    if as_of:
        base = base.where(Filing.filing_date <= as_of)
    sub = base.subquery()
    total, first, last = db.execute(
        select(func.count(), func.min(sub.c.filing_date), func.max(sub.c.filing_date))
    ).one()
    eight_ks = base.where(Filing.form_type.in_(["8-K", "8-K/A"]), Filing.filing_date >= since)
    sub8 = eight_ks.subquery()
    n8, n8_items = db.execute(select(func.count(), func.count(sub8.c["items"]))).one()
    stale_days = (ref - last).days if last else None
    return {
        "filings": total,
        "first_filed": first.isoformat() if first else None,
        "last_filed": last.isoformat() if last else None,
        "since": since.isoformat(),
        "eight_ks_since": n8,
        "eight_ks_with_items": n8_items,
        "stale": stale_days is None or stale_days > STALE_DAYS,
    }


def is_leadership_question(text: str) -> bool:
    return bool(_LEADERSHIP_Q.search(text)) and not _PAY_Q.search(text)


def leadership_answer(b: Brief) -> str:
    """Answer an officer/director question straight from the data; no model needed for a lookup."""
    name, cov = display_name(b.company.legal_name), b.coverage
    since = cov["since"]
    if b.leadership_filings:
        total = max(cov.get("leadership_since") or 0, len(b.leadership_filings))
        shown = (
            ""
            if total == len(b.leadership_filings)
            else f"; the latest {len(b.leadership_filings)}"
        )
        lines = [
            f"Recent leadership changes at {name}: {_count(total, '8-K')} with item 5.02 "
            f"(directors and officers) since {since}{shown}.",
            "",
        ]
        unverified = unread = False
        for f in b.leadership_filings:
            ref = f"[{f['citation']}]"
            if f["changes"]:
                for c in f["changes"]:
                    mark = "" if c["verified"] else " (unverified)"
                    unverified |= not c["verified"]
                    lines.append(f"• {f['filing_date']}: {c['sentence']}{mark} {ref}")
            elif f["reading"] == "ok":
                lines.append(
                    f"• {f['filing_date']}: names no individual director or officer change "
                    f"(often a pay plan or arrangement) {ref}"
                )
            else:
                unread = True
                lines.append(f"• {f['filing_date']}: filing text not read yet {ref}")
        lines.append("")
        lines.append(
            "Names and reasons are read from each filing's text by the local model and checked "
            "against it."
            + (
                ' "Unverified" means the quoted sentence could not be matched exactly.'
                if unverified
                else ""
            )
            + (" Unread filings need SEC access to be read." if unread else "")
        )
        return "\n".join(lines)
    elif cov["eight_ks_since"] and cov["eight_ks_with_items"] == cov["eight_ks_since"]:
        lines = [
            f"None of the {_count(cov['eight_ks_since'], '8-K')} loaded for {name} since {since} "
            "reports a change of directors or officers (item 5.02) [1]."
        ]
    elif cov["eight_ks_since"]:
        k, missing = cov["eight_ks_since"], cov["eight_ks_since"] - cov["eight_ks_with_items"]
        lines = [
            f"{name} has {_count(k, '8-K')} loaded since {since}, and {missing} of them "
            f"{'carries' if missing == 1 else 'carry'} no item codes, so officer or director "
            "changes can't be ruled out from this data [1].",
            "Refreshing the company from SEC adds the item codes.",
        ]
    else:
        lines = [f"No 8-K filings for {name} since {since} are loaded in this service [1]."]
        if cov["filings"]:
            lines.append(
                f"It holds {cov['filings']} filings for the company, the latest filed "
                f"{cov['last_filed']}, so it can't tell whether directors or officers changed."
            )
    return " ".join(lines)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _filing_card(f: Filing, items: list[str], n: int) -> dict:
    return {
        "form_type": f.form_type,
        "filing_date": f.filing_date.isoformat() if f.filing_date else None,
        "accession_number": f.accession_number,
        "items": [{"code": i, "title": ITEM_TITLES.get(i)} for i in items],
        "source_url": f.source_url,
        "citation": n,
    }


_LOOKUP = re.compile(
    r"^\W*(what(?:'s| is| was| were| are)?|how much|how big|show(?: me)?|tell me|give me)\b",
    re.IGNORECASE,
)
_NEEDS_REASONING = re.compile(
    r"\b(why|explain|because|reason|driv\w*|compar\w*|versus|vs\.?|risks?|outlook|"
    r"segment|guidance|margin|should|would|could|impact|cause\w*)\b",
    re.IGNORECASE,
)


def is_simple_lookup(text: str) -> bool:
    """A question that only asks for a figure ("What was Apple's revenue last year?")."""
    return bool(_LOOKUP.search(text)) and not _NEEDS_REASONING.search(text) and len(text) <= 120


def figure_answer(b: Brief, m: dict) -> str:
    """One cited sentence for one figure, with the change from the year before when known."""
    name = display_name(b.company.legal_name)
    n = m["citation"]
    text = (
        f"{name}'s {m['label'].lower()} was {m['display']} in the fiscal year ended "
        f"{m['period_end']} [{n}]"
    )
    if m.get("prior_display") and m.get("growth_pct") is not None:
        g = m["growth_pct"]
        way = "up" if g > 0 else "down" if g < 0 else "unchanged"
        change = f"{way} {abs(g):.1f}%" if g else way
        text += f", {change} from {m['prior_display']} the year before [{n}]"
    return text + "."
