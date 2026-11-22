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
    (r"\baktiengesellschaft\b", "ag"), (r"\bpublic ltd co\b", "plc"),
    (r"\bp l c\b", "plc"), (r"\bl l c\b", "llc"), (r"\bl p\b", "lp"),
)  # fmt: skip
US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
    "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split()
)


def strict_key(name: str | None) -> str:
    """The full legal name, legal form included, with spelling variants unified: "Unilever N.V."
    and "Unilever PLC" stay different; "Banco Santander, S.A." and "BANCO SANTANDER SA" agree."""
    text = re.sub(r"&", " and ", (name or "").lower())
    text = re.sub(r"['’`]", "", text)  # "Lowe's" and "LOWES" agree
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, short in _VARIANTS:
        text = re.sub(pattern, short, text)
    return text


_SEC_SUFFIX = re.compile(r"\s*/[A-Za-z]{1,5}/?\s*$")  # "INTEL CORP /DE/", "XYZ INC/NEW"


def norm_key(name: str | None) -> str:
    """K-01c: the legal name with the SEC's state suffixes ("/DE/", "/NEW/") and a leading or
    trailing "The" removed, then the strict key (legal-form spellings unified, form kept)."""
    text = _SEC_SUFFIX.sub("", name or "").strip()
    text = re.sub(r"^the\s+|,?\s+the$", "", text, flags=re.I)
    return strict_key(text)


def _same_side(issuer: Issuer, company: Company) -> bool:
    """Both in the US, or both outside it: a US filer is never matched to a foreign entity."""
    us_company = (company.state_of_incorporation or "").upper() in US_STATES
    return us_company == ((issuer.country or "").upper() == "US")


def _jurisdiction_matches(issuer: Issuer, company: Company) -> bool:
    j = (issuer.jurisdiction or "").upper()
    state = (company.state_of_incorporation or "").upper()
    return bool(j and state) and (j == state or j.endswith("-" + state))


OVERRIDES_FILE = (
    __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "lei_overrides.csv"
)


def load_overrides(db: Session, path=OVERRIDES_FILE) -> int:
    """Hand-checked links kept in the repo (app/data/lei_overrides.csv), so a rebuilt database
    keeps them. An empty lei means no link: confirmed none, or needs review (said in the note)."""
    import csv

    if not path.exists():
        return 0
    n = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            o = db.get(LeiOverride, row["cik"]) or LeiOverride(cik=row["cik"])
            o.lei, o.note = row["lei"] or None, row["note"]
            db.add(o)
            n += 1
    db.commit()
    return n


def _business_city(company: Company) -> str:
    """The city of the filer's business address as the SEC records it, upper case."""
    import json

    try:
        addr = json.loads(company.business_address or "{}") or {}
    except ValueError:
        return ""
    return (addr.get("city") or "").strip().upper()


def _cities(g) -> set[str]:
    return {x for x in ((g.hq_city or "").strip().upper(), (g.legal_city or "").strip().upper())
            if x}  # fmt: skip


def _us_candidates(by_current: dict, company: Company) -> list:
    return [g for g in by_current.get(norm_key(company.legal_name), [])
            if (g.jurisdiction or "").upper().startswith("US")]  # fmt: skip


def match_all(db: Session) -> dict:
    """Rebuild company_lei from the overrides, SEC LEIs and GLEIF names. Returns counts."""
    load_overrides(db)
    now = utcnow()
    overrides = {o.cik: o for o in db.scalars(select(LeiOverride))}
    issuers = list(db.scalars(select(Issuer).where(Issuer.lei.is_not(None))))
    by_name: dict[str, list[Issuer]] = {}
    by_strict: dict[str, list[Issuer]] = {}
    for i in issuers:
        by_name.setdefault(normalize(i.legal_name), []).append(i)
        by_strict.setdefault(strict_key(i.legal_name), []).append(i)
    from app.db.models import GleifEntity
    from app.services.lei_golden import company_jurisdictions, jurisdictions_agree

    golden: dict[str, list[GleifEntity]] = {}
    by_norm: dict[str, list[GleifEntity]] = {}
    by_current: dict[str, list[GleifEntity]] = {}  # without previous legal names
    for g in db.scalars(select(GleifEntity).where(GleifEntity.entity_status == "ACTIVE")):
        golden.setdefault(g.name_key, []).append(g)
        for k in (g.norm_keys or "").split("|"):
            if k:
                by_norm.setdefault(k.removeprefix("p:"), []).append(g)
                if not k.startswith("p:"):
                    by_current.setdefault(k, []).append(g)
    rows: list[CompanyLei] = []
    counts = {"override": 0, "sec": 0, "name_jurisdiction": 0, "gleif_name_jurisdiction": 0,
              "name_unique": 0, "gleif_name_unique": 0, "gleif_normalised_name": 0,
              "gleif_name_us_state_differs": 0, "unmatched": 0}  # fmt: skip
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
        heres = company_jurisdictions(c)  # the cover tag's state first, then the SEC field
        here = heres[0] if heres else None

        def agrees(gj, heres=heres):
            return any(jurisdictions_agree(h, gj) for h in heres)

        gold = golden.get(strict_key(c.legal_name), [])
        gold_exact = [g for g in gold if agrees(g.jurisdiction)]
        if len(exact) != 1 and len(gold_exact) == 1:
            g = gold_exact[0]
            rows.append(CompanyLei(
                cik=c.cik, lei=g.lei, match_method="gleif_name_jurisdiction", confidence="high",
                evidence=f"GLEIF legal name {g.legal_name!r} and jurisdiction {g.jurisdiction} "
                f"match the SEC name {c.legal_name!r} and place of incorporation {here}",
                matched_at=now,
            ))  # fmt: skip
            counts["gleif_name_jurisdiction"] += 1
            continue
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
        elif len(gold) == 1 and (
            not (here and gold[0].jurisdiction)
            # GLEIF gives only the country for some US funds ("US"): compatible, not confirmed
            or (
                (gold[0].jurisdiction or "").upper() == "US"
                and all(h.startswith("US-") for h in heres)
            )
        ):
            g = gold[0]  # unique name; one side's jurisdiction is unknown, so medium
            rows.append(CompanyLei(
                cik=c.cik, lei=g.lei, match_method="gleif_name_unique", confidence="medium",
                evidence=f"GLEIF legal name {g.legal_name!r} equals the SEC name "
                f"{c.legal_name!r}, legal form included, and is unique among active entities; "
                "jurisdiction not confirmed",
                matched_at=now,
            ))  # fmt: skip
            counts["gleif_name_unique"] += 1
        elif len(norm := [g for g in by_norm.get(norm_key(c.legal_name), [])
                          if agrees(g.jurisdiction)]) == 1:  # fmt: skip
            g = norm[0]  # K-01c: normalised names and the jurisdiction agree, one candidate
            exact_place = (g.jurisdiction or "").upper() in {h.upper() for h in heres}
            rows.append(CompanyLei(
                cik=c.cik, lei=g.lei, match_method="gleif_normalised_name",
                confidence="high" if exact_place else "medium",
                evidence=f"GLEIF name {g.legal_name!r} matches the SEC name {c.legal_name!r} "
                f"after normalising (state suffixes, The, legal-form spellings, other names), "
                f"and the jurisdiction {g.jurisdiction} agrees with {here}",
                matched_at=now,
            ))  # fmt: skip
            counts["gleif_normalised_name"] += 1
        elif (
            not heres
            and not re.search(r"/OLD\b", c.legal_name or "", re.I)  # a former registrant
            and len(cands := by_current.get(norm_key(c.legal_name), [])) == 1
        ):
            g = cands[0]  # the SEC record has no place of incorporation: unique name, medium
            rows.append(CompanyLei(
                cik=c.cik, lei=g.lei, match_method="gleif_normalised_name", confidence="medium",
                evidence=f"GLEIF name {g.legal_name!r} (or one of its other names) matches the "
                f"SEC name {c.legal_name!r} after normalising and is the only active entity "
                "with it; the SEC record has no place of incorporation to confirm",
                matched_at=now,
            ))  # fmt: skip
            counts["gleif_normalised_name"] += 1
        elif (
            (here or "").upper().startswith("US-")
            and not re.search(r"/OLD\b", c.legal_name or "", re.I)
            and len(cands := _us_candidates(by_current, c)) == 1
            and (city := _business_city(c))
            and city in _cities(cands[0])
        ):
            # K-01d rule (a): the SEC often records a filer's home state where GLEIF records its
            # state of incorporation (Mondelez: IL and VA). One active US entity with the name,
            # in another state, whose headquarters or legal address is in the filer's business
            # city: medium, both states and the city in the evidence
            g = cands[0]
            rows.append(CompanyLei(
                cik=c.cik, lei=g.lei, match_method="gleif_name_us_state_differs",
                confidence="medium",
                evidence=f"GLEIF name {g.legal_name!r} matches the SEC name {c.legal_name!r} "
                f"after normalising and is the only active US entity with it; GLEIF's "
                f"jurisdiction {g.jurisdiction} differs from the SEC's {here}, and its address "
                f"is in {city.title()}, the filer's business city",
                matched_at=now,
            ))  # fmt: skip
            counts["gleif_name_us_state_differs"] += 1
        else:
            counts["unmatched"] += 1
    # a K-01d match never takes an LEI another company holds, nor one two filers would share
    seen: dict[str, int] = {}
    for r in rows:
        seen[r.lei] = seen.get(r.lei, 0) + 1
    for r in [r for r in rows if r.match_method == "gleif_name_us_state_differs"]:
        if seen[r.lei] > 1:
            rows.remove(r)
            counts["gleif_name_us_state_differs"] -= 1
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
