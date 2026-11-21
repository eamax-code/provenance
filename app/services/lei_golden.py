"""Every SEC filer's LEI from the GLEIF golden copy (CC0; launch plan K-01b).

The golden copy has about 3.5 million legal entities. It is streamed once; only the entities
whose exact legal name (legal form included) matches an SEC filer's are kept, in gleif_entities.
identity.match_all() then links filers to them under the strict rules: the name and the
jurisdiction both agree (the SEC's state or country of incorporation against GLEIF's legal
jurisdiction) -> high; the name alone, unique among active entities, on the same side of the
US border -> medium. Ambiguous names stay unmatched.
"""

from __future__ import annotations

import csv
import io
import zipfile

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Company, CompanyAlias, GleifEntity, utcnow
from app.services.identity import US_STATES, norm_key, strict_key

GOLDEN_LATEST = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"
GOLDEN_MAX_BYTES = 900 * 1024 * 1024

# The SEC's codes for places of incorporation outside the US -> ISO 3166 (GLEIF's jurisdiction
# codes). Canadian provinces are ISO 3166-2, as GLEIF writes them.
SEC_COUNTRY = {
    "E9": "KY", "N4": "LU", "D8": "VG", "X0": "GB", "L2": "IE", "D0": "BM", "Y7": "GG",
    "Y9": "JE", "M0": "JP", "C3": "AU", "K3": "HK", "P7": "NL", "L3": "IL", "U0": "SG",
    "2M": "DE", "I0": "FR", "O4": "MU", "V8": "CH", "F4": "CN", "V7": "SE", "D5": "BR",
    "K7": "IN", "O5": "MX", "C5": "BS", "U3": "ES", "M5": "KR", "N0": "LR", "R1": "PA",
    "G4": "CY", "G7": "DK", "L8": "JM", "L6": "IT", "Q8": "NO", "C9": "BE", "C0": "AE",
    "T3": "ZA", "O1": "MT", "Q2": "NZ", "N8": "MY", "F5": "TW", "J1": "GI", "H9": "FI",
    "F3": "CL", "C8": "BB", "C1": "AR", "Y8": "IM", "1Z": "RU", "S1": "PT", "D1": "BZ",
    "C4": "AT", "T2": "SC", "R9": "PL", "Y0": "WS", "N2": "LI", "W1": "TH", "K5": "HU",
    "U7": "KN", "1H": "EE", "K6": "IS", "R6": "PH", "X3": "UY", "K8": "ID", "W7": "TC",
    "R5": "PE", "W8": "TR", "T0": "SA", "2N": "CZ", "1A": "AI", "N5": "MO", "F8": "CO",
    "G2": "CR", "J3": "GR", "1T": "MH", "Z4": "CA", "X1": "US",
    "A0": "CA-AB", "A1": "CA-BC", "A2": "CA-MB", "A3": "CA-NB", "A4": "CA-NL", "A5": "CA-NS",
    "A6": "CA-ON", "A7": "CA-PE", "A8": "CA-QC", "A9": "CA-SK", "B0": "CA-YT",
}  # fmt: skip


def company_jurisdiction(company: Company) -> str | None:
    """ "US-DE", "KY", "CA-ON"... from the SEC's state or country of incorporation."""
    code = (company.state_of_incorporation or "").strip()
    if code.upper() in US_STATES and code.isalpha():
        return f"US-{code.upper()}"
    return SEC_COUNTRY.get(code.upper())


def jurisdictions_agree(sec: str | None, gleif: str | None) -> bool:
    """US-DE agrees with US-DE; a country agrees with itself or any of its subdivisions; a
    Canadian federal company (CA) agrees with any province."""
    if not sec or not gleif:
        return False
    sec, gleif = sec.upper(), gleif.upper()
    if sec == gleif:
        return True
    if "-" not in sec:
        return gleif.split("-")[0] == sec
    return False


def filer_keys(db: Session) -> set[str]:
    names = set(db.scalars(select(Company.legal_name)))
    names |= set(db.scalars(select(CompanyAlias.alias).where(CompanyAlias.kind == "former")))
    return {k for k in (strict_key(n) for n in names) if k}


def filer_norm_keys(db: Session) -> set[str]:
    return {k for k in (norm_key(n) for n in db.scalars(select(Company.legal_name))) if k}


_OTHER = ("Entity.OtherEntityNames.OtherEntityName.",
          "Entity.TransliteratedOtherEntityNames.TransliteratedOtherEntityName.")  # fmt: skip


def load(db: Session, path, keys: set[str] | None = None, norms: set[str] | None = None) -> dict:
    """Stream the golden-copy zip and keep the entities whose legal name matches a filer's
    exactly, or whose legal, other or transliterated name matches one after normalising."""
    keys = keys if keys is not None else filer_keys(db)
    norms = norms if norms is not None else filer_norm_keys(db)
    now = utcnow()
    kept = seen = 0
    db.execute(delete(GleifEntity))
    batch: list[GleifEntity] = []
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(member) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            other_cols = [c for c in (reader.fieldnames or []) if c.startswith(_OTHER)
                          and c[-1].isdigit()]  # fmt: skip
            for row in reader:
                seen += 1
                name = row.get("Entity.LegalName") or ""
                key = strict_key(name)
                names = [name] + [row[c] for c in other_cols if row.get(c)]
                nkeys = {norm_key(n) for n in names} - {""}
                if key not in keys and not nkeys & norms:
                    continue
                batch.append(GleifEntity(
                    lei=row["LEI"], legal_name=name, name_key=key,
                    norm_keys="|".join(sorted(nkeys)),
                    jurisdiction=row.get("Entity.LegalJurisdiction") or None,
                    entity_status=row.get("Entity.EntityStatus") or None,
                    registration_status=row.get("Registration.RegistrationStatus") or None,
                    loaded_at=now,
                ))  # fmt: skip
                kept += 1
                if len(batch) >= 5000:
                    db.add_all(batch)
                    db.flush()
                    batch = []
    db.add_all(batch)
    db.commit()
    return {"records": seen, "kept": kept}
