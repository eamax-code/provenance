"""Ticker history from the trading symbols companies tag on their own filings (backlog K-04b).

Since 2019 every 10-K, 10-Q and 8-K cover tags each class of registered securities with
dei:TradingSymbol, dei:SecurityExchangeName and dei:Security12bTitle. The SEC's Financial
Statement and Notes data sets carry them (app.services.auditors reads them in the same pass), so
a symbol a company used before its current one can be dated from its own filings, back to 2019,
instead of only from the day a change is first seen (K-04).

A symbol the company no longer has becomes a former ticker (the alias search already reads),
valid from the first filing that tagged it to the last. Debt and other non-equity classes (notes,
debentures, preferred, warrants, units, rights) are left out, as are placeholders (N/A, NONE).
Only the registrant's undimensioned symbol is read: a company with several classes tags each
on a class-of-stock dimension, so its symbols are not used here (no false "former" ticker).
"""

from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyAlias

_NOT_EQUITY = re.compile(
    r"\bnotes?\b|debenture|%|preferred|depositary shares? each representing|warrant|\bunits?\b|"
    r"\brights?\b|bonds?|trust preferred|guarantee",
    re.I,
)
_PLACEHOLDER = {"", "N/A", "NA", "NONE", "-", "--", "NOT APPLICABLE"}
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def norm(symbol: str | None) -> str:
    """BRK.B and BRK-B are the same symbol."""
    return (symbol or "").strip().upper().replace(".", "-")


def usable(row: dict) -> bool:
    if not row.get("symbol"):
        return False
    s = norm(row.get("symbol"))
    return (
        s not in _PLACEHOLDER
        and bool(_SYMBOL.match(s))
        and not _NOT_EQUITY.search(row.get("title") or "")
        and row.get("filed_date") is not None
    )


def segments(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{cik: {symbol: {first, last}}} by filing date, equity symbols only."""
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        if not usable(r):
            continue
        s = norm(r["symbol"])
        seg = out.setdefault(r["cik"], {}).setdefault(s, {"first": r["filed_date"],
                                                          "last": r["filed_date"]})  # fmt: skip
        seg["first"] = min(seg["first"], r["filed_date"])
        seg["last"] = max(seg["last"], r["filed_date"])
    return out


def _current(company: Company) -> set[str]:
    now = {norm(company.ticker)} if company.ticker else set()
    try:
        now |= {norm(t) for t in json.loads(company.tickers or "[]") if t}
    except ValueError:
        pass
    return now


def apply(db: Session, rows: list[dict]) -> dict:
    """Store former tickers dated from the company's filings; widen the dates of ones already
    known. A symbol still current is never a former ticker."""
    segs = segments(rows)
    companies = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(list(segs))))}
    added = widened = 0
    for cik, by_symbol in segs.items():
        company = companies.get(cik)
        if company is None:
            continue
        current = _current(company)
        if not current:
            continue  # no current ticker to compare with: nothing is "former"
        for symbol, seg in by_symbol.items():
            if symbol in current:
                continue
            row = db.get(CompanyAlias, (cik, symbol))
            if row is None:
                db.add(CompanyAlias(cik=cik, alias=symbol, kind="former_ticker",
                                    valid_from=seg["first"], valid_to=seg["last"]))  # fmt: skip
                added += 1
            elif row.kind == "former_ticker":
                first = min(d for d in (row.valid_from, seg["first"]) if d)
                last = max(d for d in (row.valid_to, seg["last"]) if d)
                if (first, last) != (row.valid_from, row.valid_to):
                    row.valid_from, row.valid_to = first, last
                    widened += 1
    db.commit()
    return {"companies": len(segs), "former_tickers_added": added, "widened": widened}


def dated(rows: list[dict], cik: str) -> list[tuple[str, date, date]]:
    """A company's symbols with the first and last filing that tagged them, oldest first."""
    segs = segments(rows).get(cik, {})
    return sorted(((s, v["first"], v["last"]) for s, v in segs.items()), key=lambda x: x[1])


def apply_registrant_names(db: Session, rows: list[dict]) -> int:
    """K-06: each company's name as written on the cover of its latest report
    (dei:EntityRegistrantName), stored exactly as filed."""
    latest: dict[str, tuple] = {}
    for r in rows:
        if r.get("registrant") and r.get("filed_date"):
            cur = latest.get(r["cik"])
            if cur is None or r["filed_date"] > cur[0]:
                latest[r["cik"]] = (r["filed_date"], r["registrant"], r["accession_number"])
    n = 0
    for c in db.scalars(select(Company).where(Company.cik.in_(list(latest)))):
        _, name, accession = latest[c.cik]
        if (c.registrant_name, c.registrant_name_accession) != (name, accession):
            c.registrant_name, c.registrant_name_accession = name, accession
            n += 1
    db.commit()
    return n


INCORPORATION_TAG = "dei:EntityIncorporationStateCountryCode"


def apply_incorporation(
    db: Session, rows: list[dict], submissions: dict[str, str | None] | None = None
) -> int:
    """Each company's state of incorporation from the cover of its latest report that tags it,
    with the filing, kept in state_of_incorporation_cover beside the SEC submissions field
    (state_of_incorporation), which can hold a home state (HubSpot: NY there, DE on its cover).

    Taken only for a US state at a domestic filer: foreign filers often write an ISO country code
    there, which collides with state codes (Israel "IL", Canada "CA", Cayman "KY"). Taken only
    when the filing's own registrant name is the company's, and in a combined filing (one with
    co-registrant cover tags) never, so a parent's state never reaches a co-registrant (SL
    Green's operating partnership). `submissions` (cik -> code) restores the
    SEC field where an earlier version wrote the cover value over it."""
    from app.services.identity import US_STATES, norm_key

    latest: dict[str, tuple] = {}
    for r in rows:
        if r.get("incorporation") and r.get("filed_date"):
            cur = latest.get(r["cik"])
            if cur is None or r["filed_date"] > cur[0]:
                latest[r["cik"]] = (r["filed_date"], r["incorporation"], r["accession_number"],
                                    r.get("registrant"), r.get("combined"))  # fmt: skip
    submissions = submissions or {}
    n = 0
    stmt = select(Company).where(
        Company.cik.in_(list(latest))
        | Company.state_of_incorporation_cover.is_not(None)
        | (Company.state_of_incorporation_source == INCORPORATION_TAG)
    )
    for c in db.scalars(stmt):
        sec = submissions.get(c.cik, c.state_of_incorporation)
        cover = accession = None
        found = latest.get(c.cik)
        if found:
            _, state, acc, registrant, combined = found
            domestic = (sec or "").upper() in US_STATES or (not sec and _us_address(c))
            names = {norm_key(c.legal_name), norm_key(c.registrant_name)} - {""}
            named = not registrant or norm_key(registrant) in names
            # a combined filing's undimensioned cover can carry the parent's state even under the
            # subsidiary's own name (SL Green OP: MD there, DE on its entity dimension): never used
            if state in US_STATES and domestic and named and not combined:
                cover, accession = state, acc
        target = (sec, cover, INCORPORATION_TAG if cover else None, accession)
        now = (c.state_of_incorporation, c.state_of_incorporation_cover,
               c.state_of_incorporation_source, c.state_of_incorporation_accession)  # fmt: skip
        if now != target:
            c.state_of_incorporation, c.state_of_incorporation_cover = target[0], target[1]
            c.state_of_incorporation_source, c.state_of_incorporation_accession = target[2:]
            n += 1
    db.commit()
    return n


def _us_address(company: Company) -> bool:
    try:
        addr = json.loads(company.business_address or "{}") or {}
    except ValueError:
        return False
    return (addr.get("country") or "").strip().lower() in ("united states", "usa", "us")


def incorporation(company: Company) -> dict | None:
    """The state of incorporation with where it comes from: the company's own cover tag and its
    filing when there is one, else the SEC submissions field."""
    from app.services.sec_client import filing_index_url

    acc = company.state_of_incorporation_accession
    if company.state_of_incorporation_cover:
        return {
            "code": company.state_of_incorporation_cover,
            "source": INCORPORATION_TAG,
            "accession_number": acc,
            "source_url": filing_index_url(company.cik, acc) if acc else None,
            "sec_submissions_code": company.state_of_incorporation,
        }
    if not company.state_of_incorporation:
        return None
    return {"code": company.state_of_incorporation, "source": "sec_submissions",
            "accession_number": None, "source_url": None,
            "sec_submissions_code": company.state_of_incorporation}  # fmt: skip


def legal_name_as_filed(company: Company) -> dict | None:
    """K-06: the exact legal name the company wrote on its latest report's cover, with the
    filing it comes from (for KYC: the string as filed, not a display form)."""
    if not company.registrant_name:
        return None
    from app.services.sec_client import filing_index_url

    acc = company.registrant_name_accession
    return {
        "name": company.registrant_name,
        "source": "dei:EntityRegistrantName",
        "accession_number": acc,
        "source_url": filing_index_url(company.cik, acc) if acc else None,
    }
