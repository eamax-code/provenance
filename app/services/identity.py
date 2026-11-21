"""SEC filers linked to their legal entity (LEI) and listings abroad (launch plan K-01).

Order of evidence, strongest first:
1. a hand-checked override (`lei_overrides`), which may also say "no LEI";
2. the LEI the SEC itself carries for the filer (submissions) - high;
3. GLEIF's legal name equal to the SEC name after normalising, and the GLEIF jurisdiction equal
   to the SEC state of incorporation (US-DE and DE) - high; the name alone and unique among
   issuers - medium.
Anything else stays unmatched; a wrong link is worse than none. Listings come from the LEI:
the instruments ESMA and the FCA list for that issuer.
"""

from __future__ import annotations

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyLei, Issuer, LeiOverride, ListedInstrument, Market, utcnow

_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co", "limited", "ltd", "plc", "llc",
    "lp", "l p", "sa", "s a", "ag", "nv", "n v", "se", "spa", "s p a", "ab", "asa", "oyj",
    "holdings", "holding", "group", "the",
)  # fmt: skip
_SUFFIX_RE = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in _SUFFIXES) + r")\b")


def normalize(name: str | None) -> str:
    """ "Apple Inc." and "APPLE INC" alike: lower case, no punctuation, no legal-form words."""
    text = re.sub(r"&", " and ", (name or "").lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = _SUFFIX_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


_VARIANTS = (
    (r"\bincorporated\b", "inc"), (r"\bcorporation\b", "corp"), (r"\bcompany\b", "co"),
    (r"\blimited\b", "ltd"), (r"\bn v\b", "nv"), (r"\bs a\b", "sa"), (r"\bs p a\b", "spa"),
    (r"\baktiengesellschaft\b", "ag"), (r"\bpublic limited co\b", "plc"),
)  # fmt: skip
US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)


def strict_key(name: str | None) -> str:
    """The full legal name, legal form included, with spelling variants unified: "Unilever N.V."
    and "Unilever PLC" stay different; "Banco Santander, S.A." and "BANCO SANTANDER SA" agree."""
    text = re.sub(r"&", " and ", (name or "").lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, short in _VARIANTS:
        text = re.sub(pattern, short, text)
    return text


def _same_side(issuer: Issuer, company: Company) -> bool:
    """Both in the US, or both outside it: a US filer is never matched to a foreign entity."""
    us_company = (company.state_of_incorporation or "").upper() in US_STATES
    return us_company == ((issuer.country or "").upper() == "US")


def _jurisdiction_matches(issuer: Issuer, company: Company) -> bool:
    j = (issuer.jurisdiction or "").upper()
    state = (company.state_of_incorporation or "").upper()
    return bool(j and state) and (j == state or j.endswith("-" + state))


def match_all(db: Session) -> dict:
    """Rebuild company_lei from the overrides, SEC LEIs and GLEIF names. Returns counts."""
    now = utcnow()
    overrides = {o.cik: o for o in db.scalars(select(LeiOverride))}
    issuers = list(db.scalars(select(Issuer).where(Issuer.lei.is_not(None))))
    by_name: dict[str, list[Issuer]] = {}
    by_strict: dict[str, list[Issuer]] = {}
    for i in issuers:
        by_name.setdefault(normalize(i.legal_name), []).append(i)
        by_strict.setdefault(strict_key(i.legal_name), []).append(i)
    rows: list[CompanyLei] = []
    counts = {"override": 0, "sec": 0, "name_jurisdiction": 0, "name_unique": 0, "unmatched": 0}
    for c in db.scalars(select(Company)):
        o = overrides.get(c.cik)
        if o is not None:
            if o.lei:
                rows.append(
                    CompanyLei(
                        cik=c.cik,
                        lei=o.lei,
                        match_method="override",
                        confidence="high",
                        evidence=o.note,
                        matched_at=now,
                    )
                )
                counts["override"] += 1
            continue
        if c.lei:
            rows.append(CompanyLei(cik=c.cik, lei=c.lei, match_method="sec", confidence="high",
                                   evidence="LEI in the SEC's record for the filer",
                                   matched_at=now))  # fmt: skip
            counts["sec"] += 1
            continue
        key = normalize(c.legal_name)
        candidates = by_name.get(key, []) if key else []
        exact = [i for i in candidates if _jurisdiction_matches(i, c)]
        if len(exact) == 1:
            i = exact[0]
            rows.append(CompanyLei(
                cik=c.cik, lei=i.lei, match_method="name_jurisdiction", confidence="high",
                evidence=f"GLEIF name {i.legal_name!r} and jurisdiction {i.jurisdiction} match the "
                f"SEC name {c.legal_name!r} and state of incorporation {c.state_of_incorporation}",
                matched_at=now,
            ))  # fmt: skip
            counts["name_jurisdiction"] += 1
        elif len(strict := by_strict.get(strict_key(c.legal_name), [])) == 1 and _same_side(
            strict[0], c
        ):
            i = strict[0]
            rows.append(CompanyLei(
                cik=c.cik, lei=i.lei, match_method="name_unique", confidence="medium",
                evidence=f"GLEIF legal name {i.legal_name!r} equals the SEC name {c.legal_name!r}, "
                "legal form included, and no other issuer has it; jurisdiction not confirmed",
                matched_at=now,
            ))  # fmt: skip
            counts["name_unique"] += 1
        else:
            counts["unmatched"] += 1
    db.execute(delete(CompanyLei))
    db.add_all(rows)
    db.commit()
    return counts


def for_company(db: Session, cik: str) -> dict | None:
    """The company's LEI, how it was matched, and its listings in Europe, the UK and Canada."""
    link = db.get(CompanyLei, cik)
    if link is None:
        return None
    issuer = db.scalar(select(Issuer).where(Issuer.lei == link.lei))
    venues = {m.mic: m for m in db.scalars(select(Market))}
    listings = []
    for r in db.scalars(
        select(ListedInstrument)
        .where(ListedInstrument.issuer_lei == link.lei)
        .order_by(ListedInstrument.first_trade_date)
    ):
        m = venues.get(r.mic)
        listings.append({
            "isin": public_isin(r.isin), "mic": r.mic, "venue": m.name if m else None,
            "symbol": r.symbol,
            "country": m.country if m else None, "status": r.status,
            "first_trade_date": r.first_trade_date.isoformat() if r.first_trade_date else None,
            "currency": r.currency,
        })  # fmt: skip
    return {
        "lei": link.lei,
        "lei_name": issuer.legal_name if issuer else None,
        "lei_jurisdiction": issuer.jurisdiction if issuer else None,
        "match_method": link.match_method,
        "confidence": link.confidence,
        "evidence": link.evidence,
        "listings": listings,
        "isins": sorted({x["isin"] for x in listings if x["isin"]}),
    }


# A US or Canadian ISIN wraps the 9-character CUSIP/CINS, which CGS licenses: never shown on
# these surfaces (the listing keeps its venue and symbol).
CUSIP_PREFIXES = ("US", "CA")


def public_isin(isin: str | None) -> str | None:
    return None if not isin or isin[:2].upper() in CUSIP_PREFIXES else isin


def cik_for_lei(db: Session, lei: str) -> str | None:
    return db.scalar(select(CompanyLei.cik).where(CompanyLei.lei == lei).limit(1))
