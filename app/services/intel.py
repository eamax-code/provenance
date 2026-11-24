"""Company intelligence brief: a deterministic, cited summary that the chat model phrases.

Every number and claim in the brief comes from stored SEC data and carries a citation number
pointing at the SEC record. The language model sees only this context (see routes_chat).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

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
from app.services.fact_normalizer import (
    METRIC_LABELS,
    currency_symbol,
    display_value,
    reporting_unit,
)
from app.services.form8k import ITEM_TITLES, LEADERSHIP_ITEM, split_items
from app.services.form_names import form_label, human_date
from app.services.point_in_time import known_by

# Every mapped metric can be asked for; the brief's headline list stays short so the model's
# context does not fill with thirty series.
BRIEF_METRICS = ("revenue", "operating_income", "net_income", "total_assets", "operating_cash_flow")
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
    r"who (?:runs|leads|heads|manages)|in charge|"
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
    facts: list = field(default_factory=list)  # C-01: the facts an answer cited, for its chips

    def cite(self, label: str, url: str) -> int:
        self.citations.append({"n": len(self.citations) + 1, "label": label, "url": url})
        return len(self.citations)

    def context(self) -> str:
        return "\n".join(self.context_lines)


_TICKER_BEFORE = {"form", "class", "series", "item", "items", "schedule", "rule", "exhibit",
                  "part", "note", "notes", "tier", "level", "type", "section", "regulation",
                  "reg", "plan", "option", "phase", "grade"}  # fmt: skip
_TICKER_AFTER = {"stock", "stocks", "shares", "share", "ticker", "price", "revenue", "revenues",
                 "sales", "earnings", "income", "profit", "eps", "margin", "margins", "results",
                 "filings", "10-k", "10-q", "debt", "cash", "assets"}  # fmt: skip


def _whole_name(hit, phrase: str) -> bool:
    """With a company already given, a name switches it only when it is the company's whole
    name or at least two of its words ("and Microsoft?", "Dominion Energy"), never one word that
    merely starts a name ("Robert" in "Werner Robert F." is not Robert Half)."""
    if hit.match_type in ("ticker", "cik", "name_exact"):
        return True
    if hit.match_type == "former_name":
        return _core_name(hit.former_name or "") == _core_name(phrase)
    return _core_name(hit.company.legal_name) == _core_name(phrase) or len(phrase.split()) >= 2


def _short_ticker_is_subject(text: str, raw: list[str], i: int, follow_up: bool) -> bool:
    """A one- or two-letter ticker ("F", "GE") counts only as the question's subject: the first
    word ("F revenue"), after "$", "ticker" or "symbol", or before "stock" or "shares". Never
    with a company already given, after a word it belongs to ("Form D", "Class A", "Item 5"),
    or as a name's initial ("Robert F.", "J. P.")."""
    if follow_up:
        return False
    w = raw[i].rstrip(".")
    prev = raw[i - 1].rstrip(".").lower() if i > 0 else ""
    nxt = raw[i + 1].rstrip(".").lower() if i + 1 < len(raw) else ""
    if prev in _TICKER_BEFORE or (len(w) == 1 and raw[i].endswith(".")):
        return False
    # "Berkshire Hathaway B shares": a share class letter after a company's name, not a ticker
    if len(w) == 1 and i > 0 and nxt in _TICKER_AFTER and raw[i - 1][:1].isupper() \
            and len(prev) >= 3 and prev not in _STOP and not prev.isdigit():  # fmt: skip
        return False
    if re.search(rf"\${re.escape(w)}\b", text) or prev in ("ticker", "symbol"):
        return True
    last = i == len(raw) - 1 and prev in ("about", "for", "of", "on")  # "Tell me about GE"
    return i == 0 or nxt in _TICKER_AFTER or last


_INITIAL = re.compile(r"^[A-Z]\.?$")
BRAND_ALIASES = Path(__file__).resolve().parents[1] / "data" / "brand_aliases.csv"


def _dots(text: str) -> str:
    """ "T. Rowe Price" and "A.O. Smith" read as "T Rowe Price" and "A O Smith"."""
    return re.sub(r"\s+", " ", re.sub(r"\.", " ", text)).strip()


@lru_cache(maxsize=1)
def _alias_patterns() -> list[tuple[re.Pattern, str, bool]]:
    """C-15: reviewed brand and name aliases (app/data/brand_aliases.csv), longest first. One of
    three letters or fewer ("HP") counts only in capitals."""
    with BRAND_ALIASES.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in sorted(rows, key=lambda r: -len(r["alias"])):
        a = _dots(r["alias"])
        short = len(a) <= 3
        out.append((re.compile(rf"(?<![\w&$-]){re.escape(a)}(?![\w&-])", 0 if short else re.I),
                    r["cik"], short))  # fmt: skip
    return out


def brand_alias(db: Session, text: str, follow_up: bool = False) -> Company | None:
    """The company a reviewed alias names ("HP" is HP Inc, "T. Rowe Price" the group), checked
    before tickers. With a company already given, a short alias never switches it."""
    plain = _dots(text)
    for pat, cik, short in _alias_patterns():
        if (short and follow_up) or not pat.search(plain):
            continue
        c = db.scalar(select(Company).where(Company.cik == cik))
        if c is not None:
            return c
    return None


def _person_words(raw: list[str]) -> set[int]:
    """C-14: words that sit in a person's name around an initial, as Forms 3, 4 and 144 give
    them ("Werner Robert F.", "Cook Timothy D", "Robert F. Werner", "J. Example"). Each is never
    a company on its own ("Robert" is not Robert Half); a longer phrase still is ("Robert W.
    Baird"). An initial after Form, Class or Item is not a name's ("Form D", "Class A")."""

    def cap(k: int) -> bool:
        w = raw[k].rstrip(".") if 0 <= k < len(raw) else ""
        return len(w) >= 2 and w[0].isupper() and w.lower() not in _TICKER_BEFORE

    out: set[int] = set()
    for i, tok in enumerate(raw):
        if not _INITIAL.match(tok) or (i > 0 and raw[i - 1].rstrip(".").lower() in _TICKER_BEFORE):
            continue
        if i + 1 < len(raw) and raw[i + 1].rstrip(".").lower() in _TICKER_AFTER:
            continue  # "Berkshire B shares": a share class
        if cap(i - 1) and cap(i - 2):  # Werner Robert F.
            out |= {i - 1, i - 2}
        if cap(i - 1) and cap(i + 1):  # Robert F. Werner
            out |= {i - 1, i + 1}
        # J. Example; two initials make a company's name ("J. B. Hunt", "H. B. Fuller")
        if tok.endswith(".") and cap(i + 1) and not cap(i - 1) \
                and not (i > 0 and _INITIAL.match(raw[i - 1])):  # fmt: skip
            out.add(i + 1)
    return out


def _variants(phrase: str) -> list[str]:
    """The phrase as typed, then without punctuation ("Coca-Cola" is COCA COLA CO, "Procter &
    Gamble" is PROCTER & GAMBLE CO or "and")."""
    out = [phrase]
    for v in (
        re.sub(r"\s+", " ", re.sub(r"[-.]", " ", phrase)).strip(),
        phrase.replace("&", "and"),
        re.sub(r"(?i)\band\b", "&", phrase),
    ):
        if v and v not in out:
            out.append(v)
    return out


# words that are in many company names and never name one alone ("Software companies over $1B")
_GENERIC_WORDS = {
    "companies", "company", "corporation", "software", "industries", "industry", "technologies",
    "technology", "systems", "energy", "financial", "bank", "banks", "bancorp", "holdings",
    "group", "international", "global", "american", "united", "national", "general", "capital",
    "pharmaceuticals", "therapeutics", "partners", "trust", "fund", "resources", "services",
    "solutions", "brands", "foods", "health", "healthcare", "insurance", "realty", "properties",
    "semiconductor", "semiconductors", "airlines", "motors", "oil", "gas", "power", "electric",
    "revenue", "income", "assets", "profit", "margin", "growth",
}  # fmt: skip
ACTIVE_DAYS = 730  # an annual report in two years makes a registrant active


def _active(db: Session, ciks: list[str]) -> set[str]:
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.db.models import MartCompany

    if not ciks:
        return set()
    since = _date.today() - _td(days=ACTIVE_DAYS)
    return set(
        db.scalars(
            select(MartCompany.cik).where(
                MartCompany.cik.in_(list(set(ciks))), MartCompany.latest_annual_report_date >= since
            )
        )
    )


def _active_starting(db: Session, phrase: str, word_start: bool) -> Company | None:
    """The largest active filer whose name starts with the phrase ("Pepsi" -> PepsiCo), or, with
    word_start, has a word starting with it ("Disney" -> Walt Disney Co)."""
    from datetime import date as _date
    from datetime import timedelta as _td

    from app.db.models import MartCompany

    low = phrase.lower()
    like = func.lower(Company.legal_name).like(_like_escape(low) + "%", escape="\\")
    if word_start:
        like = func.lower(Company.legal_name).like("% " + _like_escape(low) + "%", escape="\\")
    since = _date.today() - _td(days=ACTIVE_DAYS)
    rows = db.execute(
        select(Company, MartCompany.latest_revenue, MartCompany.reporting_currency)
        .join(MartCompany, MartCompany.cik == Company.cik)
        .where(like, MartCompany.latest_annual_report_date >= since,
               MartCompany.latest_revenue.is_not(None), MartCompany.latest_revenue > 0)
    ).all()  # fmt: skip
    # a whole word: "Disney" in Walt Disney Co, never "Industrie" inside "Industries"
    pat = re.compile(rf"(^|\s){re.escape(low)}(\b|$)") if word_start else \
        re.compile(rf"^{re.escape(low)}")  # fmt: skip
    rows = [r for r in rows if pat.search(r[0].legal_name.lower())]
    if not rows:
        return None
    return max(rows, key=lambda r: (r[2] == "USD", float(r[1])))[0]


def _like_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _successor_of(db: Session, c: Company, notes: list | None) -> Company:
    """An inactive registrant with a K-05 successor resolves to the successor, saying so."""
    from app.services import successions

    s = successions.successor(db, c.cik)
    if s is None:
        return c
    succ = db.scalar(select(Company).where(Company.cik == s.successor_cik))
    if succ is None:
        return c
    if notes is not None:
        notes.append(f"{display_name(c.legal_name, c.ticker, c.registrant_name)} is now "
                     f"{display_name(succ.legal_name, succ.ticker, succ.registrant_name)}, its "
                     f"successor registrant since {s.effective_date.isoformat()}.")  # fmt: skip
    return succ


def resolve_company(db: Session, text: str, *, follow_up: bool = False,
                    notes: list | None = None) -> Company | None:  # fmt: skip
    """Find the company a free-text question is about: ticker or CIK first, then names.

    In a follow-up (a company is already under discussion) only a clearly named company
    switches it: a ticker in capitals, a whole name, or a capitalised start of a name."""
    text = re.sub(r"['\u2019]s\b", "", text)  # "Apple's" -> "Apple"
    text = _DATES.sub(" ", text)  # "3 Nov 2026", "Mar 2025": dates, never a company
    aliased = brand_alias(db, text, follow_up)
    if aliased is not None:
        return aliased
    raw = [m.group(0) for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9.&-]*", text)]
    words = [w.rstrip(".") for w in raw]
    for i, (prev, w) in enumerate(zip(["", *words], words, strict=False)):
        # Short numbers are counts ("last 5 years"), not CIKs, unless the user says "CIK".
        cik_like = w.isdigit() and len(w) <= 10 and (len(w) >= 5 or prev.lower() == "cik")
        if (not cik_like and len(w) <= 2
                and not _short_ticker_is_subject(text, raw, i, follow_up)):  # fmt: skip
            continue  # "Form D", "Class A", "Robert F.": not Dominion, Agilent or Ford
        if cik_like or (w.isupper() and 1 <= len(w) <= 6 and w not in _ACRONYMS):
            hits, _ = search_companies(db, w, limit=1)
            if hits and hits[0].match_type in ("cik", "ticker"):
                return hits[0].company
    kept = [i for i, w in enumerate(words) if w.lower() not in _STOP]
    useful = [words[i] for i in kept]
    named = _person_words(raw)
    person = {k for k, i in enumerate(kept) if i in named}  # C-14: never a company alone
    initial = {k for k, i in enumerate(kept) if _INITIAL.match(raw[i])}
    # C-15: a run of three or more capitalised words is a person's name as filed ("Huang Jen
    # Hsun"); none of its words is a near spelling of a company on its own
    caps = [k for k, i in enumerate(kept) if raw[i][:1].isupper() and len(words[i]) >= 2]
    run_of_three = {k for k in caps if {k - 2, k - 1} <= set(caps) or {k - 1, k + 1} <= set(caps)
                    or {k + 1, k + 2} <= set(caps)}  # fmt: skip

    def names_a_person(i: int, size: int) -> bool:
        """A one- or two-word phrase made only of a person's name and initials ("Robert",
        "Robert F"): never a word start or a near spelling of a company (Robert W. Baird)."""
        span = range(i, i + size)
        return size <= 2 and any(k in person for k in span) \
            and all(k in person or k in initial for k in span)  # fmt: skip

    # Words as typed first; only then without a trailing "s" ("apples growth" means Apple), so
    # "changes at Netflix" finds Netflix before "Change" finds another company.
    for singular in (False, True):
        for size in (3, 2, 1):
            found = []
            for i in range(len(useful) - size + 1):
                if size == 1 and i in person:  # a longer phrase may name one: Robert W. Baird
                    continue
                phrase = " ".join(useful[i : i + size])
                if singular:
                    if len(phrase) <= 4 or phrase[-1] not in "sS" or phrase[-2] in "sS":
                        continue
                    phrase = phrase[:-1]
                if len(phrase) < 3:
                    continue
                for variant in _variants(phrase):
                    hits, _ = search_companies(db, variant, limit=50)
                    found += [
                        (h, variant)
                        for h in hits
                        if h.match_type in _MATCH_RANK
                        and _names_it(h, variant)
                        and not (
                            h.match_type == "ticker"
                            and variant.strip().lower() in _NOT_TICKER_WORDS
                        )
                        # with a company already given, only a ticker in capitals or a name
                        # switches it, never a word that happens to be a ticker
                        and (
                            not follow_up
                            or (
                                _named(h, variant)
                                and not (h.match_type == "ticker" and not variant.isupper())
                                and _whole_name(h, variant)
                            )
                        )
                    ]
            if found:
                # "How fast is Tesla growing": Tesla is a whole name, "fast" only starts Fastenal;
                # "the main risks for Anthropic": a named company beats a word that is a ticker;
                # an active registrant beats one with no annual report in two years ("Lucid").
                ciks = [h.company.cik for h, _ in found]
                sizes, active = _sizes(db, ciks), _active(db, ciks)
                best, phrase = max(found, key=lambda x: (
                    _named(*x), x[0].company.cik in active, _match_rank(*x),
                    _name_score(*x, sizes)))  # fmt: skip
                if best.company.cik in active:
                    if getattr(best, "successor_of", None):  # search listed it for its predecessor
                        pred = db.scalar(select(Company).where(Company.cik == best.successor_of))
                        if pred is not None:
                            _successor_of(db, pred, notes)
                    return best.company
                succ = _successor_of(db, best.company, notes)
                if succ is not best.company:
                    return succ
                if phrase[:1].isupper() and " " not in phrase:  # "Pepsi": PepsiCo, not the bottler
                    alt = _active_starting(db, phrase, word_start=False)
                    if alt is not None:
                        return alt
                return best.company
    # "Disney" starts a word of Walt Disney Co: the largest active filer, only when no name
    # starts with what was typed
    for size in (2, 1):
        for i in range(len(useful) - size + 1):
            if names_a_person(i, size):
                continue
            phrase = " ".join(useful[i : i + size])
            if (len(phrase) >= 4 and phrase[:1].isupper()
                    and not set(phrase.lower().split()) & _GENERIC_WORDS):  # fmt: skip
                hit = _active_starting(db, phrase, word_start=True)
                if hit is not None:
                    return hit
    # A typo ("Mircosoft", "amazn"): the nearest name within one or two letters; never with a
    # company already given ("Werner Robert F." is not Robert W. Baird)
    if follow_up:
        return None
    best = None
    for size in (2, 1):
        for i in range(len(useful) - size + 1):
            if names_a_person(i, size) or (size == 1 and i in run_of_three):
                continue
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
        # One capitalised word that only starts an old name ("France" in "France Telecom") is
        # too weak; the start of an old name must be at least two words ("Philip Morris").
        core = core_name(hit.former_name or "")
        return core == phrase.lower() or (
            phrase[:1].isupper() and " " in phrase.strip() and core.startswith(phrase.lower() + " ")
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


_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DATES = re.compile(
    rf"\b\d{{1,2}}\s+{_MONTH}(?:,?\s+\d{{4}})?\b"  # 3 Nov 2026, 3 Nov
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?(?:\s+\d{{4}})?\b"  # Nov 3, 2026; Nov 3
    rf"|\b{_MONTH}\s+\d{{4}}\b",  # Nov 2026
    re.IGNORECASE,
)

# words that are dates or everyday words, never a ticker typed as a word ("3 Nov 2026" is not
# NOV Inc.): month and weekday abbreviations and names
_NOT_TICKER_WORDS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "january", "february", "march", "april", "june", "july", "august", "september", "october",
    "november", "december", "mon", "tue", "wed", "thu", "fri", "sat", "sun", "today", "now",
    # the words of SEC documents ("Form 144" is not FormFactor, FORM)
    "form", "forms", "item", "items", "class", "series", "schedule", "exhibit", "rule", "note",
    "part", "filing", "filings", "report",
}  # fmt: skip


def _ticker_word(hit, phrase: str) -> bool:
    """A capitalised word that is the company's ticker and starts its name ("Meta" is META,
    Meta Platforms; "Snap" is SNAP): it names the company as surely as the ticker in capitals."""
    c = hit.company
    if phrase.strip().lower() in _NOT_TICKER_WORDS:
        return False
    return (hit.match_type == "ticker" and phrase[:1].isupper() and " " not in phrase.strip()
            and bool(c.ticker) and c.ticker.upper() == phrase.upper()
            and _core_name(c.legal_name).startswith(phrase.lower()))  # fmt: skip


def _named(hit, phrase: str) -> bool:
    """Whether the phrase clearly names this company rather than merely starting its name."""
    if hit.match_type == "ticker":
        return phrase.isupper() or _ticker_word(hit, phrase)
    if hit.match_type == "former_name":
        return _core_name(hit.former_name or "") == _core_name(phrase) or phrase[:1].isupper()
    if hit.match_type == "name_exact" or _core_name(hit.company.legal_name) == _core_name(phrase):
        return True
    return phrase[:1].isupper()


def _match_rank(hit, phrase: str) -> int:
    # A lower-case word that happens to be a ticker ("fast" is FAST) is no stronger than a prefix.
    if hit.match_type == "ticker" and not phrase.isupper():
        return _MATCH_RANK["ticker"] if _ticker_word(hit, phrase) else 1
    return _MATCH_RANK[hit.match_type]


_core_name = core_name


def _name_score(hit, phrase: str, sizes: dict | None = None) -> tuple:
    """ "Apple" means Apple Inc., not Apple REIT Six; "Hawaiian Electric" the listed parent;
    between names that start the same way, the larger filer by latest annual revenue ("Meta"
    is not Meta Data Ltd), then the shorter name."""
    c = hit.company
    size = (sizes or {}).get(c.cik) or 0
    return (bool(c.ticker), _core_name(c.legal_name) == _core_name(phrase), size,
            -len(c.legal_name))  # fmt: skip


def _sizes(db: Session, ciks: list[str]) -> dict[str, float]:
    """Latest annual revenue in US dollars (other currencies count as unknown: never converted)."""
    from app.db.models import MartCompany

    if not ciks:
        return {}
    rows = db.execute(select(MartCompany.cik, MartCompany.latest_revenue,
                             MartCompany.reporting_currency)
                      .where(MartCompany.cik.in_(list(set(ciks))))).all()  # fmt: skip
    return {c: float(v) for c, v, cur in rows if v is not None and cur == "USD"}


_KEEP_UPPER = {"LLC", "PLC", "LP", "NV", "SA", "AG", "SE", "USA", "US", "II", "III", "IV"}


def display_name(legal_name: str, ticker: str | None = None, registrant: str | None = None) -> str:
    """ "COSTCO WHOLESALE CORP /NEW" reads as "Costco Wholesale Corp" in an answer (K-06):
    the company's own cover-page name when it is written with real casing ("Apple Inc."), else
    the SEC's conformed name without its state suffix ("TOYOTA MOTOR CORP/" -> "Toyota Motor
    Corp"), title-cased, with the word that is the company's ticker kept in capitals ("SAP SE")."""
    from app.services.cover_names import strip_state_suffix, unglue

    if registrant and registrant != registrant.upper():
        return strip_state_suffix(unglue(registrant))
    name = strip_state_suffix(unglue(legal_name))
    if name != name.upper():
        return name
    root = (ticker or "").upper().replace(".", "-").split("-")[0]
    words: list[str] = []
    for w in name.split():
        if w == "COM" and words:  # the SEC drops the dot: "AMAZON COM INC" is Amazon.com
            words[-1] += ".com"
            continue
        keep = (w in _KEEP_UPPER or not w[:1].isalpha() or (root and w == root)
                or bool(re.fullmatch(r"[A-Z]{1,2}/[A-Z]{1,2}", w)))  # S/A, A/S, I/O  # fmt: skip
        words.append(w if keep else w.capitalize())
    return " ".join(words)


def display(v: Decimal | float, metric: str, unit: str | None = None) -> str:
    return display_value(v, metric, unit)


def money(v: Decimal | float, unit: str | None = None) -> str:
    """$1.2 billion; EUR 36.8 billion in a company's own currency (D-04)."""
    from app.services.fact_normalizer import MINUS

    x, sym = float(v), currency_symbol(unit)
    sign, a = (MINUS if x < 0 else ""), abs(x)
    for div, word in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if a >= div:
            return f"{sign}{sym}{a / div:,.1f} {word}"
    return f"{sign}{sym}{a:,.0f}"


def annual_series(db: Session, cik: str, metric: str, as_of: date | None) -> list[FinancialFact]:
    """One reported annual figure per fiscal year, newest first, in the unit the company
    reports the metric in (D-04: not a convenience translation)."""
    stmt = select(FinancialFact).where(
        FinancialFact.cik == cik,
        FinancialFact.metric == metric,
        FinancialFact.period_class == "annual",
        FinancialFact.derived.is_(False),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.value.is_not(None),
    )
    if as_of:
        stmt = known_by(stmt, as_of)
    rows = list(db.scalars(stmt))
    unit = reporting_unit(rows, metric)

    def rank(f: FinancialFact) -> tuple:
        # An annual report beats a proxy's pay-versus-performance table for the same year.
        return (f.form_type in ANNUAL_FORMS, f.filed_date or date.min, f.accession_number or "")

    latest: dict[date, FinancialFact] = {}
    for f in rows:
        if f.unit != unit:
            continue
        cur = latest.get(f.period_end)
        if cur is None or rank(f) > rank(cur):
            latest[f.period_end] = f
    return [latest[k] for k in sorted(latest, reverse=True)]


def build_brief(db: Session, company: Company, as_of: date | None = None) -> Brief:
    b = Brief(company=company, as_of=as_of)
    # named, not linked: only sec.gov/Archives filings are ever links (PM, 2026-11-23)
    n = b.cite(f"SEC EDGAR company record, CIK {company.cik}", None)
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
            f"{human_date(cov['first_filed'])} to {human_date(cov['last_filed'])}; 8-K filings "
            f"since {human_date(cov['since'])}: {cov['eight_ks_since']}. Anything filed after "
            f"{human_date(cov['last_filed'])} is not loaded."
        )
    else:
        b.context_lines.append(f"[{n}] No filings are loaded in this service for the company.")

    for metric in BRIEF_METRICS:
        label = METRIC_LABELS[metric]
        series = annual_series(db, company.cik, metric, as_of)
        if not series:
            continue
        cur = series[0]
        prev = series[1] if len(series) > 1 else None
        growth = None
        if prev is not None and prev.value:
            growth = round(float((cur.value - prev.value) / abs(prev.value)) * 100, 1)
        n = b.cite(f"{label}, {cur.form_type} filed {human_date(cur.filed_date)}", cur.source_url)
        b.metrics.append(
            {
                "metric": metric,
                "label": label,
                "period_end": cur.period_end.isoformat(),
                "value": float(cur.value),
                "display": money(cur.value, cur.unit),
                "unit": cur.unit,
                "currency": cur.unit.split("/")[0],
                "prior_period_end": prev.period_end.isoformat() if prev else None,
                "prior_value": float(prev.value) if prev else None,
                "prior_display": money(prev.value, prev.unit) if prev else None,
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
        shown = money(cur.value, cur.unit)
        line = f"[{n}] {label}, fiscal year ended {human_date(cur.period_end)}: {shown}"
        if prev is not None:
            before = money(prev.value, prev.unit)
            line += f"; prior year (ended {human_date(prev.period_end)}) {before}"
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
        n = b.cite(f"{f.form_type} filed {human_date(f.filing_date)}", f.source_url)
        b.filings.append(_filing_card(f, items, n))
        line = f"[{n}] Filing: {form_label(f.form_type)}, filed {human_date(f.filing_date)}"
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
        n = b.cite(f"8-K item 5.02 filed {human_date(f.filing_date)}", f.source_url)
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
                    f"[{n}] Leadership change in 8-K filed {human_date(f.filing_date)} "
                    f"(item 5.02): {officer_changes.describe(c)}{flag}"
                )
        else:
            b.context_lines.append(
                f"[{n}] Leadership filing: 8-K filed {human_date(f.filing_date)} under item 5.02 "
                "(directors or officers). "
                + (
                    "It names no individual director or officer change."
                    if card["reading"] == "ok"
                    else "Its text has not been read here."
                )
            )
    # cards whose text is read first; an unread filing is never the first card (S-01)
    b.leadership_filings.sort(key=lambda c: c["reading"] not in ("ok",) and not c["changes"])
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
    since_h = human_date(since)
    if b.leadership_filings:
        total = max(cov.get("leadership_since") or 0, len(b.leadership_filings))
        read = [f for f in b.leadership_filings if f["changes"] or f["reading"] == "ok"]
        unread = [f for f in b.leadership_filings if f not in read]
        head = (
            f"{_words(total).capitalize()} {'filing reports' if total == 1 else 'filings report'}"
            f" director or officer changes at {name} (8-K item 5.02) since {since_h}"
        )
        if read and total > len(read):
            head += f"; the latest {_words(len(read))} {'is' if len(read) == 1 else 'are'} below"
        lines = [head + ".", ""]
        unverified = False
        for f in read:
            ref, when = f"[{f['citation']}]", human_date(f["filing_date"])
            if f["changes"]:
                for c in f["changes"]:
                    mark = "" if c["verified"] else " (unverified)"
                    unverified |= not c["verified"]
                    lines.append(f"• {when}: {c['sentence']}{mark} {ref}")
            else:
                lines.append(
                    f"• {when}: names no individual director or officer change "
                    f"(often a pay plan or arrangement) {ref}"
                )
        if unread:  # never lead with a filing whose text is not read (the demo never fetches)
            lines.append(
                "Also filed, not read yet: "
                + "; ".join(
                    f"8-K of {human_date(f['filing_date'])} [{f['citation']}]" for f in unread
                )  # fmt: skip
                + "."
            )
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
            f"None of the {_count(cov['eight_ks_since'], '8-K')} loaded for {name} since {since_h} "
            "reports a change of directors or officers (item 5.02) [1]."
        ]
    elif cov["eight_ks_since"]:
        k, missing = cov["eight_ks_since"], cov["eight_ks_since"] - cov["eight_ks_with_items"]
        lines = [
            f"{name} has {_count(k, '8-K')} loaded since {since_h}, and {missing} of them "
            f"{'carries' if missing == 1 else 'carry'} no item codes, so officer or director "
            "changes can't be ruled out from this data [1].",
            "Refreshing the company from SEC adds the item codes.",
        ]
    else:
        lines = [f"No 8-K filings for {name} since {since_h} are loaded in this service [1]."]
        if cov["filings"]:
            lines.append(
                f"It holds {cov['filings']} filings for the company, the latest filed "
                f"{cov['last_filed']}, so it can't tell whether directors or officers changed."
            )
    return " ".join(lines)


_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _words(n: int) -> str:
    """Small counts in words, so they never run into the dates beside them."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else f"{n:,}"


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


# C-07: a figure question is answered from the stored facts without a model, for any of the
# metrics and any fiscal year the question names ("Apple net income 2023", "AAPL revenue"):
# one sentence citing the filing, or a sentence saying the filings loaded here do not hold it.
_ASKED_YEAR = re.compile(r"\b(?:fy\s?|fiscal(?: year)?\s+)?((?:19|20)\d{2})\b", re.IGNORECASE)
_FIGURE_REASONING = re.compile(
    r"\b(why|explain|because|reason|driv\w*|compar\w*|versus|vs\.?|risks?|outlook|segment|"
    r"guidance|should|would|could|impact|cause\w*|forecast|predict|expect\w*|next year)\b",
    re.IGNORECASE,
)
_MARGIN_Q = re.compile(r"\b(gross|operating|net|profit)?\s*margins?\b", re.IGNORECASE)
_MARGIN_PARTS = {"gross": "gross_profit", "operating": "operating_income", "net": "net_income"}
# labels read as plurals: "total assets were", not "was"
PLURAL_METRICS = {
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "cash_and_equivalents",
    "dividends_paid",
    "share_repurchases",
    "shares_outstanding",
    "shares_basic_weighted",
    "shares_diluted_weighted",
}


def asked_year(text: str) -> int | None:
    m = _ASKED_YEAR.search(text)
    return int(m.group(1)) if m else None


def is_figure_question(text: str) -> bool:
    """Asks for a figure, not an explanation ("Apple net income 2023", "What was ...?")."""
    return len(text) <= 120 and not _FIGURE_REASONING.search(text)


def asked_margin(text: str) -> str | None:
    """'operating', 'gross' or 'net' when the question asks for a margin (operating by
    default)."""
    m = _MARGIN_Q.search(text)
    if not m:
        return None
    word = (m.group(1) or "operating").lower()
    return "net" if word == "profit" else word


def _cite_fact(b: Brief, f: FinancialFact) -> int:
    same = next((c["n"] for c in b.citations if c["url"] == f.source_url), None)
    n = same or b.cite(f"{f.form_type} filed {f.filed_date}", f.source_url)
    if all(x is not f for x, _ in b.facts):
        b.facts.append((f, n))
    return n


def annual_fact(db: Session, company: Company, metric: str, year: int | None,
                as_of: date | None) -> FinancialFact | None:  # fmt: skip
    """The reported annual figure for a fiscal year (the latest when no year is named)."""
    rows = annual_series(db, company.cik, metric, as_of)
    if year is None:
        return rows[0] if rows else None
    from app.services import periods

    fye = periods.convention(company)
    return next((f for f in rows if periods.fiscal_year(f.period_end, fye) == year), None)


def figure_for(db: Session, b: Brief, metric: str, year: int | None, as_of: date | None) -> str:
    from app.services.fact_normalizer import METRIC_LABELS

    c = b.company
    name = display_name(c.legal_name, c.ticker, c.registrant_name)
    label = METRIC_LABELS.get(metric, metric).lower()
    f = annual_fact(db, b.company, metric, year, as_of)
    if f is None:
        when = f" for fiscal {year}" if year else ""
        return f"{name}'s {label}{when} is not in the filings loaded here."
    n = _cite_fact(b, f)
    verb = "were" if metric in PLURAL_METRICS else "was"
    text = (f"{name}'s {label} {verb} {display(f.value, metric, f.unit)} in the fiscal year ended "
            f"{f.period_end} [{n}]")  # fmt: skip
    rows = annual_series(db, b.company.cik, metric, as_of)
    older = [r for r in rows if r.period_end < f.period_end and r.unit == f.unit]
    prior = older[0] if older else None
    if prior is not None and prior.value and (f.period_end - prior.period_end).days < 400:
        g = (float(f.value) - float(prior.value)) / abs(float(prior.value)) * 100
        way = "up" if g > 0 else "down" if g < 0 else "unchanged"
        change = f"{way} {abs(g):.1f}%" if round(g, 1) else "little changed"
        text += (f", {change} from {display(prior.value, metric, prior.unit)} the year before "
                 f"[{_cite_fact(b, prior)}]")  # fmt: skip
    return text + "."


def margin_for(db: Session, b: Brief, kind: str, year: int | None, as_of: date | None) -> str:
    """A margin derived from two reported figures of the same fiscal year and currency."""
    c = b.company
    name, part = display_name(c.legal_name, c.ticker, c.registrant_name), _MARGIN_PARTS[kind]
    top = annual_fact(db, b.company, "revenue", year, as_of)
    num = None
    if top is not None:
        num = next((f for f in annual_series(db, b.company.cik, part, as_of)
                    if f.period_end == top.period_end and f.unit == top.unit), None)  # fmt: skip
    if top is None or num is None or not top.value:
        when = f" for fiscal {year}" if year else ""
        return f"{name}'s {kind} margin{when} cannot be worked out from the filings loaded here."
    pct = float(num.value) / float(top.value) * 100
    n_num, n_top = _cite_fact(b, num), _cite_fact(b, top)
    cites = f"[{n_num}]" if n_num == n_top else f"[{n_num}] [{n_top}]"
    from app.services.fact_normalizer import METRIC_LABELS

    return (f"{name}'s {kind} margin was {pct:.1f}% in the fiscal year ended {top.period_end}: "
            f"{METRIC_LABELS[part].lower()} of {display(num.value, part, num.unit)} on revenue of "
            f"{display(top.value, 'revenue', top.unit)} (derived) {cites}.")  # fmt: skip


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
