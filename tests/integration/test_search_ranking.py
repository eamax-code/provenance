"""/v1/companies/search ranks the company people mean first (2026-11-24, ui's palette check):
the same rules as chat's resolver; a successor stands in for an inactive predecessor."""

from __future__ import annotations

from datetime import date

from app.db.models import CompanyAlias, RegistrantSuccession
from app.services.company_lookup import search_companies
from tests.integration.test_resolve_ranking import OLD, _co


def _names(db, q, n=3):
    return [(h.company.legal_name, h.match_type) for h in search_companies(db, q, n)[0]]


def test_search_ranking(db, client, auth):
    _co(db, "0000900107", "GOOGLE INC.", None, None, OLD)
    _co(db, "0000900108", "Alphabet Inc.", "GOOGL", 400_000_000_000)
    _co(db, "0000900109", "LUCID INC", None, None, OLD)
    _co(db, "0000900110", "Lucid Group, Inc.", "LCID", 1_000_000_000)
    _co(db, "0000900113", "Coca-Cola Consolidated, Inc.", "COKE", 7_000_000_000)
    _co(db, "0000900114", "COCA COLA CO", "KO", 47_000_000_000)
    _co(db, "0000900115", "Walt Disney Co", "DIS", 94_000_000_000)
    _co(db, "0000900117", "TWDC Enterprises 18 Corp.", None, None)
    _co(db, "0000900118", "FORD MOTOR CO", "F", 187_000_000_000)
    _co(db, "0000900119", "Forward Industries, Inc.", "FWDI", 18_000_000)
    db.add(CompanyAlias(cik="0000900117", alias="WALT DISNEY CO/", kind="former"))
    db.add(CompanyAlias(cik="0000900119", alias="FORD", kind="former_ticker"))
    db.add(RegistrantSuccession(
        predecessor_cik="0000900107", successor_cik="0000900108", effective_date=date(2015, 10, 2),
        evidence_accession="0001193125-15-336550", evidence_form="8-K",
        match_method="holding_company_reorganization", confidence="high"))  # fmt: skip
    db.commit()
    assert _names(db, "Google") == [("Alphabet Inc.", "former_name"), ("GOOGLE INC.", "name_exact")]
    assert _names(db, "Disney")[0][0] == "Walt Disney Co"
    assert _names(db, "Coca-Cola")[0][0] == "COCA COLA CO"
    assert _names(db, "Lucid")[0][0] == "Lucid Group, Inc."
    assert _names(db, "Ford")[0][0] == "FORD MOTOR CO"  # FORD typed as a word, not the ticker
    assert _names(db, "FORD")[0][0] == "Forward Industries, Inc."  # typed as a ticker
    body = client.get("/v1/companies/search?q=Google&limit=3", headers=auth).json()
    first = body["data"][0]
    assert first["cik"] == "0000900108" and first["matched_name"] == "GOOGLE INC."
