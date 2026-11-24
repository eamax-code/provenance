"""Q-03: open-market insider buys and sales across companies (docs/contracts/insider-screener.md).

One row per original Form 4, transaction code (P or S) and security class: those lines are added
up. Amendments (Form 4/A) never make a row; an original names the 4/As for the same issuer, a
reporting owner of it and the same period (amended_by). Lines dated after their filing, or more
than three years before it, are as-filed errors and left out. Information, not signals.
"""

from __future__ import annotations

import bisect
import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Date, and_, case, func, select
from sqlalchemy.orm import Session

from app.db.models import InsiderActivity, InsiderFiling, InsiderTransaction
from app.services import insiders
from app.services.insider_activity import CLUSTER
from app.services.sec_client import filing_index_url

TYPES = {"buy": "P", "sell": "S"}
ROLES = ("director", "officer", "ten_percent_owner", "other", "ceo", "cfo")
MAX_DAYS = 366
PRICE_OUTLIER = 20  # times the median price of the issuer's lines of the class nearby
OUTLIER_DAYS = 30  # days either side of a row's trades for that median
GIANT_VALUE = 5e9  # a row this large needs a year of the class's prices to back it
GIANT_DAYS = 365
STALE_DAYS = 3 * 365  # a line dated this long before its filing is an as-filed error
MAX_LIMIT = 100
MAX_OFFSET = 5000
_CHUNK = 1000
DISCLAIMER = "Information, not signals. Not investment advice."


@dataclass
class Screen:
    codes: set[str]
    since: date
    until: date
    as_of: date | None = None
    min_value: float | None = None
    max_value: float | None = None
    roles: set[str] = field(default_factory=set)
    titles: list[str] = field(default_factory=list)  # any of these, as words of the title
    cik: str | None = None
    owner_cik: str | None = None
    plan_10b5_1: bool | None = None
    cluster: bool = False
    allowed: set[str] | None = None  # the demo key's showcase companies


_OWNER_COLS = (
    InsiderFiling.accession_number, InsiderFiling.issuer_cik, InsiderFiling.owner_cik,
    InsiderFiling.owner_name, InsiderFiling.is_director, InsiderFiling.is_officer,
    InsiderFiling.is_ten_percent_owner, InsiderFiling.is_other, InsiderFiling.officer_title,
    InsiderFiling.other_text, InsiderFiling.form_type, InsiderFiling.filing_date,
    InsiderFiling.period_of_report, InsiderFiling.plan_10b5_1,
)  # fmt: skip


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _title_match(titles: list[str], officer_title: str | None) -> bool:
    """Any of the alternatives as whole words of the title as filed, case ignored ("cfo" finds
    "EVP & CFO", not "CFOX")."""
    t = officer_title or ""
    for a in titles:
        for m in re.finditer(r"\b" + r"\s+".join(map(re.escape, a.split())) + r"\b", t, re.I):
            if not _NOT_THE_OFFICER.search(t[: m.start()]) and not _NOT_AFTER.match(t[m.end() :]):
                return True
    return False


# "Strategic Advisor to CEO", "Assistant to the CFO", "Deputy CEO": not the officer named (ui's
# live pass, 24 Nov)
_NOT_THE_OFFICER = re.compile(r"\b(?:advis[eo]r|assistant|aide|counsel(?:or)?|chief of staff)"
                              r"\s+to\s+(?:the\s+)?$|\b(?:deputy|vice|associate|assistant)\s*$",
                              re.IGNORECASE)  # fmt: skip
_NOT_AFTER = re.compile(r"\s*(?:assistant|advis[eo]r|aide)\b", re.IGNORECASE)  # "CEO Assistant"


# role=ceo,cfo (PM decision, 24 Nov): the company's own principal executive and financial
# officers. The title is split into parts (commas, &, /, "and", dashes, brackets). The part
# naming the CEO or CFO may add only interim, acting or co; every other part must hold a role
# word ("SVP Finance", "Chief Risk Officer", "Director (Class II)"), so a part that is a
# business, unit or place ("CEO, Medicare Advantage", "President and CEO, Retail", "CEO - Asia
# Pacific") leaves the title out, as do unit and other-person words anywhere (division, group,
# bank, subsidiary, deputy, advisor, assistant, former, designate, elect, "to the", "of X"). A
# missed row is better than a wrong one: title= still finds it.
_CEO = re.compile(r"\b(?:ceo|(?:principal|chief)\s+exec(?:utive|\.)?(?:\s+off(?:icer|\.|ice)?)?"
                  r")(?![a-z])", re.I)  # fmt: skip
_CFO = re.compile(r"\b(?:cfo|(?:principal|chief)\s+financial(?:\s+off(?:icer|\.|ice)?)?)(?![a-z])",
                  re.I)  # fmt: skip
_SPLIT = re.compile(r"\s*(?:[,;/&|()+]|\band\b|\s[-\u2013\u2014]\s?|-\s)\s*", re.I)
_LEAD_OK = {"interim", "acting", "co", "ad", "int", "the", "company"}
_ROLE_WORDS = set("""
officer off ofc ofcr offr chief president pres chairman chair chairwoman chairperson chrm chrmn
chmn director dir directors md vp evp svp sevp csvp sr senior vice treasurer treas secretary sec
controller contr counsel founder cofounder member trustee ceo cfo coo cao cto cio cco clo cbo cso
cro cmo cpo gm head principal board bod executive exec manager partner cob ctlr secy pao pfo
peo cc gc bd
""".split())  # fmt: skip
_NEUTRAL = set("""
see remarks footnote footnotes note class i ii iii the of and co interim acting finance
accounting treasury corp corporate dev development strategy admin administration
""".split())  # fmt: skip
_NOT_COMPANY = re.compile(r"\b(?:division\w*|segment|unit|group|region\w*|subsidiar\w*|bank\w*|"
                          r"advis[eo]r|aide|former|designate|elect|emerit\w*)\b"
                          r"|\bassistant\s+(?:to|ceo|cfo|chief)\b|\bexecutive\s+assistant\b"
                          r"|\bto\s+(?:the\s+)?(?:ceo|cfo|chief)\b", re.I)  # fmt: skip
_WORD = re.compile(r"[a-z]+")


def principal_roles(title: str | None) -> set[str]:
    """{"ceo", "cfo"} or a part of it: the company's own principal officers in the title."""
    # "E.V.P." is evp, "Chief Exec. Officer" chief exec officer
    t = " ".join((title or "").lower().replace("co-", "co ").replace(".", "").split())
    if not (_CEO.search(t) or _CFO.search(t)) or _NOT_COMPANY.search(t):
        return set()
    for m in re.finditer(r"\bof\s+(?:the\s+)?([a-z]+)", t):
        if m.group(1) not in _ROLE_WORDS | _NEUTRAL | {"company", "directors"}:
            return set()  # "CEO of Manager", "CEO of Logistics": somebody else's officer
    found: set[str] = set()
    for part in (x for x in _SPLIT.split(t) if x and x.strip()):
        hits = [(k, rx) for k, rx in (("ceo", _CEO), ("cfo", _CFO)) if rx.search(part)]
        if hits:
            rest = part
            for _, rx in hits:
                rest = rx.sub(" ", rest)
            if "deputy" in _WORD.findall(rest):
                continue  # "Deputy CEO & CFO": the deputy part is not the CEO; the CFO counts
            # beside the CEO or CFO, only company-level role words ("Sr VP Chief Financial
            # Officer"); "head" there names a business ("CEO Head Universal Banking")
            if any(w not in _LEAD_OK and (w not in _ROLE_WORDS or w == "head")
                   for w in _WORD.findall(rest)):  # fmt: skip
                return set()  # "Group CEO", "KFC Division CEO", "CEO Head Universal Banking"
            found |= {k for k, _ in hits}
        else:
            words = _WORD.findall(part)
            if words and not (set(words) & _ROLE_WORDS) and not set(words) <= _NEUTRAL:
                return set()  # a business, unit or place: "Medicare Advantage", "Retail"
    return found


def _matches(f, s: Screen) -> bool:
    """The owner meets the screen's role, title and owner filters (listed first on its row)."""
    if s.owner_cik and f.owner_cik != s.owner_cik:
        return False
    if s.roles and not _role_keys(f) & s.roles:
        return False
    return not (s.titles and not _title_match(s.titles, f.officer_title))


def _role_keys(f: InsiderFiling) -> set[str]:
    keys = set(principal_roles(f.officer_title)) if f.is_officer else set()
    if f.is_director:
        keys.add("director")
    if f.is_officer:
        keys.add("officer")
    if f.is_ten_percent_owner:
        keys.add("ten_percent_owner")
    if f.is_other:
        keys.add("other")
    return keys


def screen(db: Session, s: Screen) -> tuple[list[dict], dict]:
    """Every row of the screen (unpaged, unsorted; finish() completes a page) and counts for the
    notes. Lines are added up in SQL per Form 4, code and class, with the value filters there, so
    a year of sales (about 80,000 lines) never passes through Python; owners are read only for
    the groups that remain."""
    t = InsiderTransaction
    priced = and_(t.price > 0, t.shares.is_not(None))
    title = func.coalesce(t.security_title, "")
    value = func.sum(case((priced, t.shares * t.price)))
    q = (
        select(t.accession_number, t.issuer_cik, t.trans_code, title.label("title"),
               func.count().label("lines"), func.sum(t.shares).label("shares"),
               value.label("value"), func.sum(case((priced, t.shares))).label("priced_shares"),
               func.count(case((priced, 1))).label("priced_lines"),
               func.min(t.trans_date, type_=Date).label("first"),
               func.max(t.trans_date, type_=Date).label("last"),
               func.count(func.distinct(t.direct_indirect)).label("n_di"),
               func.max(t.direct_indirect).label("di"))
        .where(t.trans_code.in_(sorted(s.codes)), t.is_derivative.is_(False),
               t.trans_date >= s.since, t.trans_date <= s.until)
        .group_by(t.accession_number, t.issuer_cik, t.trans_code, title)
    )  # fmt: skip
    if s.cik:
        q = q.where(t.issuer_cik == s.cik)
    if s.allowed is not None:
        q = q.where(t.issuer_cik.in_(sorted(s.allowed)))
    if s.min_value is not None:
        q = q.having(value >= s.min_value)
    if s.max_value is not None:
        q = q.having(value <= s.max_value)
    groups = list(db.execute(q))
    owners: dict[str, list] = defaultdict(list)
    for part in _chunks(sorted({g.accession_number for g in groups})):
        for f in db.execute(select(*_OWNER_COLS).where(InsiderFiling.accession_number.in_(part))):
            owners[f.accession_number].append(f)
    counts = {"filed_errors": 0, "amendments": 0, "unpaired_amendments": 0, "duplicates": 0}
    amended: dict[str, list] = {}
    rows = []
    for g in groups:
        fs = sorted(owners.get(g.accession_number, []), key=lambda f: (not _matches(f, s),
                                                                       f.owner_cik))  # fmt: skip
        if not fs:
            continue
        f0 = fs[0]
        if s.as_of and f0.filing_date > s.as_of:
            continue
        if f0.form_type != "4":
            if f0.form_type == "4/A":
                amended[g.accession_number] = fs
            continue
        if s.owner_cik and s.owner_cik not in {f.owner_cik for f in fs}:
            continue
        if s.roles and not any(_role_keys(f) & s.roles for f in fs):
            continue
        if s.titles and not any(_title_match(s.titles, f.officer_title) for f in fs):
            continue
        if s.plan_10b5_1 is not None and f0.plan_10b5_1 is not s.plan_10b5_1:
            continue
        agg = dict(g._mapping)
        stale = f0.filing_date - timedelta(STALE_DAYS)
        if g.last > f0.filing_date or g.first < stale:  # as-filed date errors: rare, redone
            agg, dropped = _regroup(db, g, f0.filing_date, stale, s)
            counts["filed_errors"] += dropped
            if agg is None:
                continue
        rows.append(_row(agg, fs))
    rows = _collapse_duplicates(rows, counts)
    counts["amendments"] = len(amended)
    counts["unpaired_amendments"] = _unpaired(db, amended)
    _flag_price_outliers(db, rows, s)
    if s.cluster or any(r["trans_code"] == "P" for r in rows):
        _add_clusters(db, rows, s)
    if s.cluster:
        rows = [r for r in rows if r["cluster"]]
    if s.min_value is not None:
        rows = [r for r in rows if _ranked_value(r) is not None and r["value"] >= s.min_value]
    if s.max_value is not None:
        rows = [r for r in rows if _ranked_value(r) is not None and r["value"] <= s.max_value]
    return rows, counts


def _lines(db: Session, acc: str, issuer: str, code: str, title: str, s: Screen | None = None):
    t = InsiderTransaction
    q = select(t.trans_date, t.shares, t.price, t.shares_after, t.direct_indirect, t.row_key).where(
        t.accession_number == acc, t.issuer_cik == issuer, t.trans_code == code,
        t.is_derivative.is_(False), func.coalesce(t.security_title, "") == title)  # fmt: skip
    if s is not None:
        q = q.where(t.trans_date >= s.since, t.trans_date <= s.until)
    return sorted(db.execute(q), key=lambda x: (x.trans_date, x.row_key))


def _regroup(db: Session, g, filed: date, stale: date, s: Screen) -> tuple[dict | None, int]:
    """The group's lines again, without those dated after the filing or more than three years
    before it."""
    ls = _lines(db, g.accession_number, g.issuer_cik, g.trans_code, g.title, s)
    keep = [x for x in ls if stale <= x.trans_date <= filed]
    if not keep:
        return None, len(ls)
    pr = [x for x in keep if x.price is not None and float(x.price) > 0 and x.shares is not None]
    di = {x.direct_indirect for x in keep if x.direct_indirect}
    return {
        "accession_number": g.accession_number, "issuer_cik": g.issuer_cik,
        "trans_code": g.trans_code, "title": g.title, "lines": len(keep),
        "shares": sum(float(x.shares or 0) for x in keep),
        "value": sum(float(x.shares) * float(x.price) for x in pr) if pr else None,
        "priced_shares": sum(float(x.shares) for x in pr), "priced_lines": len(pr),
        "first": keep[0].trans_date, "last": keep[-1].trans_date, "n_di": len(di),
        "di": next(iter(di)) if di else None,
    }, len(ls) - len(keep)  # fmt: skip


def finish(db: Session, page: list[dict], s: Screen) -> None:
    """For the rows shown: amended_by, shares_after (the last line's holding) and
    holdings_change_pct (reading them for every row of a screen cost more than the screen)."""
    _add_amendments(db, page)
    for r in page:
        acc = r["filing"]["accession_number"]
        ls = _lines(db, acc, r["issuer_cik"], r["trans_code"], r["_title"], s)
        ls = [x for x in ls if r["first_date"] <= x.trans_date <= r["last_date"]]
        after = ls[-1].shares_after if ls else None
        r["shares_after"] = float(after) if after is not None else None
        change = None
        if after is not None and r["direct_indirect"] != "mixed":
            sh = r["shares"]
            before = float(after) + sh if r["trans_code"] == "S" else float(after) - sh
            if before > 0:
                change = round((-sh if r["trans_code"] == "S" else sh) / before * 100, 2)
        r["holdings_change_pct"] = change


def _filings_for(db: Session, form: str, keys: set[tuple]) -> list:
    """Filings of `form` whose (issuer, owner, period) is in keys: read by issuer and filing
    date (the issuer-and-date index; an OR of thousands of triples was slow), matched here."""
    if not keys:
        return []
    first = min(k[2] for k in keys)
    out = []
    for part in _chunks(sorted({k[0] for k in keys}), 500):
        q = select(*_OWNER_COLS).where(InsiderFiling.issuer_cik.in_(part),
                                       InsiderFiling.filing_date >= first,
                                       InsiderFiling.form_type == form)  # fmt: skip
        out += [f for f in db.execute(q) if (f.issuer_cik, f.owner_cik, f.period_of_report) in keys]
    return out


def _unpaired(db: Session, amended: dict[str, list]) -> int:
    """Form 4/As in the screen with no stored original Form 4 (same issuer, a reporting owner of
    it, same period, filed by the 4/A's date): not shown (Q-03b)."""
    keys = {(f.issuer_cik, f.owner_cik, f.period_of_report) for fs in amended.values() for f in fs
            if f.period_of_report}  # fmt: skip
    originals: dict[tuple, list[date]] = defaultdict(list)
    for f in _filings_for(db, "4", keys):
        originals[(f.issuer_cik, f.owner_cik, f.period_of_report)].append(f.filing_date)
    n = 0
    for fs in amended.values():
        dates = [
            (d, f.filing_date)
            for f in fs
            for d in originals.get((f.issuer_cik, f.owner_cik, f.period_of_report), [])
        ]
        if not any(d <= filed for d, filed in dates):
            n += 1
    return n


def unquote(title: str | None) -> str | None:
    """A class name as filed, without the CSV quoting some data-set rows kept:
    '"Class A Common Stock (""Common Stock"")"' is 'Class A Common Stock ("Common Stock")'."""
    if title and len(title) >= 2 and title[0] == title[-1] == '"':
        return title[1:-1].replace('""', '"')
    return title


def _row(g: dict, fs: list) -> dict:
    shares = float(g["shares"] or 0)
    value = float(g["value"]) if g["value"] is not None else None
    priced_shares = float(g["priced_shares"] or 0)
    code, issuer, acc = g["trans_code"], g["issuer_cik"], g["accession_number"]
    f0 = fs[0]
    return {
        "issuer_cik": issuer,
        "owners": [
            {
                "cik": f.owner_cik,
                "name": insiders.display_name(f.owner_name),
                "role": insiders.role_label(insiders._flags(f)),
                "is_director": f.is_director,
                "is_officer": f.is_officer,
                "is_ten_percent_owner": f.is_ten_percent_owner,
                "officer_title": f.officer_title,
            }
            for f in fs
        ],  # fmt: skip
        "type": "buy" if code == "P" else "sell",
        "trans_code": code,
        "security_title": unquote(g["title"]) or None,
        "_title": g["title"],  # as stored, to read the lines again (finish)
        "first_date": g["first"],
        "last_date": g["last"],
        "lines": g["lines"],
        "shares": shares,
        "average_price": round(value / priced_shares, 4) if value and priced_shares else None,
        "value": round(value, 2) if value is not None else None,
        "value_partial": 0 < g["priced_lines"] < g["lines"],
        "price_outlier": False,
        "shares_after": None,
        "holdings_change_pct": None,
        "direct_indirect": "mixed" if g["n_di"] > 1 else g["di"],
        "plan_10b5_1": f0.plan_10b5_1,
        "cluster": None,
        "amended_by": [],
        "duplicate_filings": [],
        "period": f0.period_of_report,
        "filing": {
            "accession_number": acc,
            "form": f0.form_type,
            "filed_date": f0.filing_date,
            "source_url": filing_index_url(issuer, acc),
        },  # fmt: skip
    }


def _add_clusters(db: Session, rows: list[dict], s: Screen) -> None:
    """A purchase counted in an F-03 cluster-buying event: same issuer, its owner among the
    event's insiders, its first trade from the event's first trade to the event's date."""
    buys = [r for r in rows if r["trans_code"] == "P"]
    issuers = sorted({r["issuer_cik"] for r in buys})
    events: dict[str, list[dict]] = defaultdict(list)
    for part in _chunks(issuers):
        for e in db.scalars(select(InsiderActivity).where(
                InsiderActivity.activity_type == CLUSTER, InsiderActivity.cik.in_(part),
                InsiderActivity.activity_date >= s.since)):  # fmt: skip
            if s.as_of and e.filing_date > s.as_of:
                continue
            detail = json.loads(e.detail or "{}")
            first = detail.get("first_trade")
            events[e.cik].append({
                "event_date": e.activity_date,
                "first_trade": date.fromisoformat(first) if first else e.activity_date,
                "insiders": detail.get("insiders"),
                "owners": {o.get("owner_cik") for o in json.loads(e.owners or "[]")},
                "event_filing": {"accession_number": e.accession_number,
                                 "source_url": e.source_url},
            })  # fmt: skip
    for r in buys:
        mine = {o["cik"] for o in r["owners"]}
        for e in sorted(events.get(r["issuer_cik"], []), key=lambda e: e["event_date"]):
            if mine & e["owners"] and e["first_trade"] <= r["first_date"] <= e["event_date"]:
                r["cluster"] = {k: e[k] for k in ("event_date", "insiders", "first_trade",
                                                  "event_filing")}  # fmt: skip
                break


def _add_amendments(db: Session, rows: list[dict]) -> None:
    """Form 4/As for the same issuer, a reporting owner of the row and the same period, filed
    on or after the original."""
    for r in rows:
        r["amended_by"] = []  # idempotent: a row passed twice lists each 4/A once
    want = {(r["issuer_cik"], o["cik"], r["period"]) for r in rows if r["period"]
            for o in r["owners"]}  # fmt: skip
    if not want:
        return
    found: dict[tuple, list] = defaultdict(list)
    for f in _filings_for(db, "4/A", want):
        found[(f.issuer_cik, f.owner_cik, f.period_of_report)].append(f)
    for r in rows:
        seen = set()
        for o in r["owners"]:
            for f in found.get((r["issuer_cik"], o["cik"], r["period"]), []):
                if f.accession_number in seen or f.filing_date < r["filing"]["filed_date"]:
                    continue
                seen.add(f.accession_number)
                r["amended_by"].append({
                    "accession_number": f.accession_number, "filed_date": f.filing_date,
                    "source_url": filing_index_url(r["issuer_cik"], f.accession_number),
                })  # fmt: skip
        r["amended_by"].sort(key=lambda a: (a["filed_date"], a["accession_number"]))


def _collapse_duplicates(rows: list[dict], counts: dict) -> list[dict]:
    """The same Form 4 filed twice the same day (same issuer, owners, code, class, lines,
    shares, value and dates) is one trade: the first accession stays, the others are listed in
    its duplicate_filings (one such pair counted $1.86 billion twice)."""
    first: dict[tuple, dict] = {}
    out = []
    for r in sorted(rows, key=lambda r: r["filing"]["accession_number"]):
        k = (r["issuer_cik"], frozenset(o["cik"] for o in r["owners"]), r["trans_code"],
             r["security_title"], r["lines"], r["shares"], r["value"], r["first_date"],
             r["last_date"], r["filing"]["filed_date"])  # fmt: skip
        if k in first:
            first[k]["duplicate_filings"].append(
                {"accession_number": r["filing"]["accession_number"],
                 "source_url": r["filing"]["source_url"]})  # fmt: skip
            counts["duplicates"] += 1
            continue
        first[k] = r
        out.append(r)
    return out


def _ranked_value(r: dict) -> float | None:
    """The value used to filter and sort: none for a price outlier (shown as filed)."""
    return None if r["price_outlier"] else r["value"]


def _flag_price_outliers(db: Session, rows: list[dict], s: Screen) -> None:
    """price_outlier: the row's average price is more than PRICE_OUTLIER times above or below the
    median price of the same issuer's lines of the same class within OUTLIER_DAYS of the row's
    trade dates (4 or more lines; fewer: no flag). Per class (Berkshire A and B differ 1,500x;
    preferred beside common) and local in time (a 1:50 reverse split inside a year), so the flag
    belongs to the row, not to the query. Filed prices with the total in the price box made a
    15,000-share sale worth $18.5 billion; the row stays, with its value as filed, but out of
    value filters and value ranking."""
    t = InsiderTransaction
    keys = {(r["issuer_cik"], r["_title"]) for r in rows if r["average_price"]}
    issuers = sorted({k[0] for k in keys})
    lo, hi = s.since - timedelta(OUTLIER_DAYS), s.until + timedelta(OUTLIER_DAYS)
    lines: dict[tuple, list[tuple[date, float]]] = defaultdict(list)
    title = func.coalesce(t.security_title, "")
    for part in _chunks(issuers):
        q = select(t.issuer_cik, title, t.trans_date, t.price).where(
            t.issuer_cik.in_(part), t.trans_code.in_(("P", "S")), t.is_derivative.is_(False),
            t.price > 0, t.trans_date >= lo, t.trans_date <= hi)  # fmt: skip
        for issuer, ti, day, price in db.execute(q):
            if (issuer, ti) in keys:
                lines[(issuer, ti)].append((day, float(price)))
    for v in lines.values():
        v.sort()
    for r in rows:
        r["price_outlier"] = False
        got = lines.get((r["issuer_cik"], r["_title"]))
        if not r["average_price"] or not got:
            continue
        days = [d for d, _ in got]
        i = bisect.bisect_left(days, r["first_date"] - timedelta(OUTLIER_DAYS))
        j = bisect.bisect_right(days, r["last_date"] + timedelta(OUTLIER_DAYS))
        near = [p for _, p in got[i:j]]
        if len(near) < 4:
            continue
        ratio = r["average_price"] / statistics.median(near)
        r["price_outlier"] = not (1 / PRICE_OUTLIER <= ratio <= PRICE_OUTLIER)
    _flag_unsupported_giants(db, rows)


def _flag_unsupported_giants(db: Session, rows: list[dict]) -> None:
    """A row worth GIANT_VALUE or more is a price outlier unless 4 or more lines of the same
    issuer and class within a year have a median price within PRICE_OUTLIER times of its price.
    The largest real open-market sale in a year was $3.77 billion (a foundation selling in a
    takeover); thin classes hid a $18.5 billion and a $1.6 quadrillion "sale" from the local rule
    (one line, 40 million shares at $40 million)."""
    t = InsiderTransaction
    title = func.coalesce(t.security_title, "")
    for r in rows:
        if r["price_outlier"] or (r["value"] or 0) < GIANT_VALUE or not r["average_price"]:
            continue
        q = select(t.price).where(
            t.issuer_cik == r["issuer_cik"], title == r["_title"], t.trans_code.in_(("P", "S")),
            t.is_derivative.is_(False), t.price > 0,
            t.trans_date >= r["first_date"] - timedelta(GIANT_DAYS),
            t.trans_date <= r["last_date"] + timedelta(GIANT_DAYS))  # fmt: skip
        prices = [float(p) for p in db.scalars(q)]
        ratio = r["average_price"] / statistics.median(prices) if len(prices) >= 4 else None
        r["price_outlier"] = ratio is None or not (1 / PRICE_OUTLIER <= ratio <= PRICE_OUTLIER)


def sort_rows(rows: list[dict], how: str) -> list[dict]:
    if how == "value":
        return sorted(rows, key=lambda r: (_ranked_value(r) is None, -(_ranked_value(r) or 0),
                                           -r["last_date"].toordinal(),
                                           r["filing"]["accession_number"]))  # fmt: skip
    if how == "filed":
        return sorted(rows, key=lambda r: (-r["filing"]["filed_date"].toordinal(),
                                           -r["last_date"].toordinal(),
                                           r["filing"]["accession_number"],
                                           r["trans_code"], r["security_title"] or ""))  # fmt: skip
    return sorted(rows, key=lambda r: (-r["last_date"].toordinal(),
                                       -r["filing"]["filed_date"].toordinal(),
                                       r["filing"]["accession_number"], r["trans_code"],
                                       r["security_title"] or ""))  # fmt: skip
