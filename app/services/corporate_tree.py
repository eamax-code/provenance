"""The corporate tree of one company (D-14, docs/contracts/corporate-tree.md): GLEIF Level 2
parents or reporting exceptions, the entities that report this company as their parent, and
the latest exhibit 21 subsidiaries with an LEI where one matches exactly. GLEIF is named as the
source (CC0) and never linked."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    CompanyLei,
    GleifException,
    GleifName,
    GleifRelationship,
    Subsidiary,
    SubsidiaryLei,
)
from app.services.gleif_level2 import REASONS
from app.services.intel import display_name
from app.services.sec_client import filing_index_url

NOTES = [
    "Parents and GLEIF children are from GLEIF Level 2 relationship data (golden copy, CC0) as "
    "the entities report them; subsidiaries are as listed in the latest exhibit 21. An exhibit "
    "21 subsidiary has an LEI only when exactly one GLEIF entity has the same legal name and "
    "jurisdiction.",
]
MATCH = {"sec": "reported by the company to the SEC", "override": "checked by hand",
         "name_jurisdiction": "name_and_jurisdiction",
         "gleif_name_jurisdiction": "name_and_jurisdiction"}  # fmt: skip


def _names(db: Session, leis: set[str]) -> dict[str, GleifName]:
    if not leis:
        return {}
    return {n.lei: n for n in db.scalars(select(GleifName).where(GleifName.lei.in_(leis)))}


def _ciks(db: Session, leis: set[str]) -> dict[str, str]:
    if not leis:
        return {}
    return dict(db.execute(select(CompanyLei.lei, CompanyLei.cik)
                           .where(CompanyLei.lei.in_(leis))).all())  # fmt: skip


def _node(lei: str, names: dict, ciks: dict) -> dict:
    n = names.get(lei)
    return {"lei": lei, "name": n.legal_name if n else None,
            "jurisdiction": n.jurisdiction if n else None,
            "status": n.entity_status if n else None, "cik": ciks.get(lei)}  # fmt: skip


def for_company(db: Session, company: Company, children_limit: int = 100,
                subsidiaries_limit: int = 200) -> dict:  # fmt: skip
    link = db.scalar(select(CompanyLei).where(CompanyLei.cik == company.cik))
    lei = link.lei if link else None
    entity = {"lei": lei, "name": display_name(company.legal_name, company.ticker,
                                               company.registrant_name),
              "jurisdiction": None, "lei_match": MATCH.get(link.match_method, link.match_method)
              if link else None}  # fmt: skip
    parents = {"direct": None, "ultimate": None, "exceptions": []}
    children = {"total": 0, "data": []}
    if lei:
        own = db.get(GleifName, lei)
        if own is not None:
            entity["jurisdiction"] = own.jurisdiction
        rels = list(db.scalars(select(GleifRelationship).where(GleifRelationship.child_lei == lei)))
        kids_q = select(GleifRelationship).where(GleifRelationship.parent_lei == lei,
                                                 GleifRelationship.child_lei != lei)  # fmt: skip
        kids = list(db.scalars(kids_q))
        direct_kids = {k.child_lei for k in kids if k.kind == "direct"}
        all_kids = {k.child_lei for k in kids}
        leis = {r.parent_lei for r in rels} | all_kids
        names, ciks = _names(db, leis), _ciks(db, leis)
        for r in rels:
            parents[r.kind] = {**_node(r.parent_lei, names, ciks),
                               "relationship_status": r.status,
                               "period_start": r.period_start.isoformat() if r.period_start
                               else None}  # fmt: skip
        for e in db.scalars(select(GleifException).where(GleifException.lei == lei)):
            if parents.get(e.kind) is None:
                parents["exceptions"].append({"kind": e.kind, "reason": e.reason,
                                              "text": REASONS.get(e.reason, e.reason)})
        nodes = [{**_node(k, names, ciks),
                  "relationship": "direct" if k in direct_kids else "ultimate_only"}
                 for k in all_kids]  # fmt: skip
        nodes.sort(key=lambda n: (n["relationship"] != "direct", (n["name"] or "").lower()))
        children = {"total": len(nodes), "data": nodes[:children_limit]}
    latest = db.scalar(select(func.max(Subsidiary.filing_date))
                       .where(Subsidiary.cik == company.cik))  # fmt: skip
    subsidiaries = {"total": 0, "filing": None, "data": []}
    if latest is not None:
        rows = list(db.scalars(select(Subsidiary).where(Subsidiary.cik == company.cik,
                                                        Subsidiary.filing_date == latest)
                               .order_by(Subsidiary.position)))  # fmt: skip
        links = dict(db.execute(select(SubsidiaryLei.subsidiary_id, SubsidiaryLei.lei).where(
            SubsidiaryLei.subsidiary_id.in_([r.id for r in rows]))).all()) if rows else {}
        first = rows[0] if rows else None
        subsidiaries = {
            "total": len(rows),
            "filing": {"accession_number": first.accession_number, "form": first.form_type,
                       "filed_date": first.filing_date.isoformat(),
                       "source_url": first.source_url
                       or filing_index_url(company.cik, first.accession_number)}
            if first else None,
            "data": [{"name": r.name, "jurisdiction": r.jurisdiction, "lei": links.get(r.id),
                      "lei_match": "exact_name_and_jurisdiction" if r.id in links else None}
                     for r in rows[:subsidiaries_limit]],
        }  # fmt: skip
    return {"cik": company.cik, "entity": entity, "parents": parents, "children": children,
            "subsidiaries": subsidiaries, "notes": NOTES}  # fmt: skip
