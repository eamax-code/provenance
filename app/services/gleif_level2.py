"""GLEIF Level 2 and the corporate tree (D-14, docs/contracts/corporate-tree.md).

From the GLEIF golden copy (CC0; GLEIF is named, never linked):
* relationship records: each entity's direct and ultimate accounting-consolidation parent, as
  the entity reports it, kept where a filer's LEI is the child or the parent;
* reporting exceptions: why an entity gives no parent (NATURAL_PERSONS, NON_CONSOLIDATING, ...);
* the names, jurisdictions and statuses of the LEIs those refer to, from the Level 1 file.
Exhibit 21 subsidiaries (the latest list per company) are linked to an LEI only when exactly
one GLEIF entity has the same normalised legal name and the jurisdiction agrees.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    CompanyLei,
    GleifException,
    GleifName,
    GleifRelationship,
    Subsidiary,
    SubsidiaryLei,
)
from app.services.identity import norm_key

KINDS = {"IS_DIRECTLY_CONSOLIDATED_BY": "direct", "IS_ULTIMATELY_CONSOLIDATED_BY": "ultimate"}
EXC_KINDS = {"DIRECT_ACCOUNTING_CONSOLIDATION_PARENT": "direct",
             "ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT": "ultimate"}  # fmt: skip
REASONS = {
    "NATURAL_PERSONS": "The parent is one or more natural persons.",
    "NON_CONSOLIDATING": "The parent does not consolidate this entity in its accounts.",
    "NO_KNOWN_PERSON": "There is no known person controlling this entity.",
    "NON_PUBLIC": "The parent's identity is not public (the entity gives a legal reason).",
    "BINDING_LEGAL_COMMITMENTS": "Binding legal commitments prevent disclosing the parent.",
    "LEGAL_OBSTACLES": "Legal obstacles prevent disclosing the parent.",
    "DISCLOSURE_DETRIMENTAL": "Disclosing the parent would be detrimental to the entity.",
    "DETRIMENT_NOT_EXCLUDED": "Detriment from disclosing the parent cannot be excluded.",
    "CONSENT_NOT_OBTAINED": "The parent's consent to disclose was not obtained.",
}

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "puerto rico": "PR",
}  # fmt: skip
CA_PROVINCES = {"alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB",
                "newfoundland and labrador": "NL", "nova scotia": "NS", "ontario": "ON",
                "quebec": "QC", "saskatchewan": "SK"}  # fmt: skip
COUNTRIES = {
    "united states": "US", "usa": "US", "u.s.": "US", "united kingdom": "GB", "uk": "GB",
    "england": "GB", "england and wales": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "ireland": "IE", "canada": "CA", "mexico": "MX", "brazil": "BR",
    "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "germany": "DE",
    "france": "FR", "italy": "IT", "spain": "ES", "portugal": "PT", "netherlands": "NL",
    "the netherlands": "NL", "belgium": "BE", "luxembourg": "LU", "switzerland": "CH",
    "austria": "AT", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI",
    "poland": "PL", "czech republic": "CZ", "hungary": "HU", "romania": "RO", "greece": "GR",
    "turkey": "TR", "russia": "RU", "israel": "IL", "united arab emirates": "AE",
    "saudi arabia": "SA", "south africa": "ZA", "egypt": "EG", "nigeria": "NG", "kenya": "KE",
    "india": "IN", "china": "CN", "people's republic of china": "CN", "prc": "CN",
    "hong kong": "HK", "taiwan": "TW", "japan": "JP", "korea": "KR", "south korea": "KR",
    "republic of korea": "KR", "singapore": "SG", "malaysia": "MY", "thailand": "TH",
    "indonesia": "ID", "philippines": "PH", "vietnam": "VN", "australia": "AU",
    "new zealand": "NZ", "cayman islands": "KY", "bermuda": "BM", "british virgin islands": "VG",
    "bahamas": "BS", "barbados": "BB", "jersey": "JE", "guernsey": "GG", "isle of man": "IM",
    "gibraltar": "GI", "malta": "MT", "cyprus": "CY", "mauritius": "MU", "panama": "PA",
    "costa rica": "CR", "uruguay": "UY", "liechtenstein": "LI", "monaco": "MC",
    "slovakia": "SK", "slovenia": "SI", "croatia": "HR", "bulgaria": "BG", "serbia": "RS",
    "estonia": "EE", "latvia": "LV", "lithuania": "LT", "ukraine": "UA", "iceland": "IS",
    "morocco": "MA", "qatar": "QA", "kuwait": "KW", "bahrain": "BH", "oman": "OM",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "macau": "MO",
}  # fmt: skip


def jurisdiction_code(text: str | None) -> str | None:
    """'Delaware' -> US-DE, 'England and Wales' -> GB, 'Ontario' -> CA-ON, 'Cayman Islands' ->
    KY. None when the text is not one recognised place."""
    t = re.sub(r"[^a-z' .]", " ", (text or "").lower()).strip(" .")
    t = " ".join(t.replace("the ", "", 1).split()) if t.startswith("the ") else " ".join(t.split())
    if not t:
        return None
    if t in US_STATES:
        return f"US-{US_STATES[t]}"
    if t in CA_PROVINCES:
        return f"CA-{CA_PROVINCES[t]}"
    return COUNTRIES.get(t)


def agree(ex21: str | None, gleif: str | None) -> bool:
    """US-DE matches US-DE; a country matches the country and its subdivisions (GB, GB-ENG)."""
    if not ex21 or not gleif:
        return False
    return gleif == ex21 or gleif.startswith(ex21 + "-")


def _rows(path):
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(member) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def _ymd(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def parse_level2(db: Session, rr_path, repex_path) -> tuple[list[dict], list[dict]]:
    ours = set(db.scalars(select(CompanyLei.lei)))
    rels = []
    for r in _rows(rr_path):
        kind = KINDS.get(r.get("Relationship.RelationshipType", ""))
        if kind is None:
            continue
        child, parent = r["Relationship.StartNode.NodeID"], r["Relationship.EndNode.NodeID"]
        if child not in ours and parent not in ours:
            continue
        rels.append({"child_lei": child, "kind": kind, "parent_lei": parent,
                     "status": r.get("Relationship.RelationshipStatus") or None,
                     "period_start": _ymd(r.get("Relationship.Period.1.startDate"))})  # fmt: skip
    exc = []
    for r in _rows(repex_path):
        kind = EXC_KINDS.get(r.get("Exception.Category", ""))
        if kind is None or r["LEI"] not in ours:
            continue
        exc.append({"lei": r["LEI"], "kind": kind, "reason": r.get("Exception.Reason.1") or ""})
    return rels, exc


def latest_subsidiaries(db: Session) -> list[Subsidiary]:
    """The rows of each company's latest exhibit 21 list."""
    latest = (select(Subsidiary.cik, func.max(Subsidiary.filing_date).label("d"))
              .group_by(Subsidiary.cik).subquery())  # fmt: skip
    return list(db.scalars(select(Subsidiary).join(
        latest, (latest.c.cik == Subsidiary.cik) & (latest.c.d == Subsidiary.filing_date))))


def scan_level1(path, leis: set[str], sub_keys: set[str]) -> tuple[dict, dict]:
    """One pass over the Level 1 file: names for the wanted LEIs, and every entity whose
    normalised legal name is one of the subsidiary names (norm -> [(lei, jurisdiction, name,
    status)])."""
    names, by_key = {}, {}
    for r in _rows(path):
        lei = r["LEI"]
        name = r.get("Entity.LegalName") or ""
        jur = r.get("Entity.LegalJurisdiction") or None
        status = r.get("Entity.EntityStatus") or None
        if lei in leis:
            names[lei] = {"lei": lei, "legal_name": name, "jurisdiction": jur,
                          "entity_status": status}  # fmt: skip
        k = norm_key(name)
        if k in sub_keys:
            by_key.setdefault(k, []).append((lei, jur, name, status))
    return names, by_key


def match_subsidiaries(subs: list[Subsidiary], by_key: dict) -> list[dict]:
    out = []
    for s in subs:
        code = jurisdiction_code(s.jurisdiction)
        cands = [c for c in by_key.get(norm_key(s.name), []) if agree(code, c[1])]
        active = [c for c in cands if c[3] != "INACTIVE"] or cands
        if len(active) == 1:
            out.append({"subsidiary_id": s.id, "lei": active[0][0]})
    return out


def store(db: Session, rels, exc, names, links) -> dict:
    for model in (GleifRelationship, GleifException, GleifName, SubsidiaryLei):
        db.execute(delete(model))
    for model, rows in ((GleifRelationship, rels), (GleifException, exc),
                        (GleifName, list(names.values())), (SubsidiaryLei, links)):  # fmt: skip
        for i in range(0, len(rows), 5000):
            db.execute(insert(model), rows[i : i + 5000])
    db.commit()
    return {"relationships": len(rels), "exceptions": len(exc), "names": len(names),
            "subsidiary_links": len(links)}  # fmt: skip
