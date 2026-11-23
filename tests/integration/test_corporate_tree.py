"""D-14: the corporate tree (docs/contracts/corporate-tree.md)."""

from __future__ import annotations

from datetime import date

from app.db.models import (
    CompanyLei,
    GleifException,
    GleifName,
    GleifRelationship,
    Subsidiary,
    SubsidiaryLei,
)
from app.services import gleif_level2 as L2

CIK = "0000320193"
ME, PARENT, KID, KID2 = "HWUPKR0MPOU8FGXBT394", "PARENTLEI00000000001", "KIDLEI00000000000001", \
    "KIDLEI00000000000002"  # fmt: skip


def test_jurisdictions():
    assert L2.jurisdiction_code("Delaware") == "US-DE"
    assert L2.jurisdiction_code("England and Wales") == "GB"
    assert L2.jurisdiction_code("Ontario") == "CA-ON"
    assert L2.jurisdiction_code("The Netherlands") == "NL"
    assert L2.jurisdiction_code("Delaware and New York") is None  # not one place
    assert L2.agree("GB", "GB-ENG") and L2.agree("US-DE", "US-DE")
    assert not L2.agree("US-DE", "US-NY") and not L2.agree(None, "US")


def test_subsidiary_links_need_one_exact_name_and_jurisdiction():
    subs = [Subsidiary(id=1, name="Apple Operations Limited", jurisdiction="Ireland"),
            Subsidiary(id=2, name="Apple Sales Inc.", jurisdiction="Delaware"),
            Subsidiary(id=3, name="Braeburn Capital, Inc.", jurisdiction="Nevada")]  # fmt: skip
    from app.services.identity import norm_key

    by_key = {
        norm_key("APPLE OPERATIONS LIMITED"): [("L1", "IE", "APPLE OPERATIONS LIMITED", "ACTIVE")],
        norm_key("Apple Sales Inc."): [("L2", "US-DE", "Apple Sales Inc.", "ACTIVE"),
                                       ("L3", "US-DE", "Apple Sales Inc.", "ACTIVE")],  # two
        norm_key("Braeburn Capital, Inc."): [("L4", "US-CA", "Braeburn Capital, Inc.", "ACTIVE")],
    }  # fmt: skip
    assert L2.match_subsidiaries(subs, by_key) == [{"subsidiary_id": 1, "lei": "L1"}]


def test_corporate_tree_endpoint(client, auth, db, ingested_aapl):
    db.add(CompanyLei(cik=CIK, lei=ME, match_method="sec", confidence="high", evidence="x"))
    db.add_all([GleifName(lei=ME, legal_name="Apple Inc.", jurisdiction="US-CA"),
                GleifName(lei=PARENT, legal_name="Parent Holdings Ltd", jurisdiction="GB"),
                GleifName(lei=KID, legal_name="Apple Operations Limited", jurisdiction="IE"),
                GleifName(lei=KID2, legal_name="Deep Sub BV", jurisdiction="NL")])  # fmt: skip
    db.add(GleifRelationship(child_lei=ME, kind="direct", parent_lei=PARENT, status="ACTIVE",
                             period_start=date(2020, 1, 1)))  # fmt: skip
    db.add(GleifException(lei=ME, kind="ultimate", reason="NO_KNOWN_PERSON"))
    db.add(GleifRelationship(child_lei=KID, kind="direct", parent_lei=ME, status="ACTIVE"))
    db.add(GleifRelationship(child_lei=KID2, kind="ultimate", parent_lei=ME, status="ACTIVE"))
    for i, (name, jur) in enumerate((("Apple Operations Limited", "Ireland"),
                                     ("Braeburn Capital, Inc.", "Nevada"))):  # fmt: skip
        db.add(
            Subsidiary(
                id=100 + i,
                cik=CIK,
                accession_number="0000320193-25-000079",
                form_type="10-K",
                filing_date=date(2025, 10, 31),
                exhibit="EX-21.1",
                position=i,
                name=name,
                jurisdiction=jur,
                source_url="https://www.sec.gov/Archives/edgar/data/320193/x/ex21.htm",
            )
        )
    db.add(SubsidiaryLei(subsidiary_id=100, lei=KID))
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/corporate-tree", headers=auth).json()
    assert body["entity"]["lei"] == ME and body["entity"]["lei_match"].startswith("reported")
    assert body["parents"]["direct"]["name"] == "Parent Holdings Ltd"
    assert body["parents"]["ultimate"] is None
    assert body["parents"]["exceptions"] == [{"kind": "ultimate", "reason": "NO_KNOWN_PERSON",
        "text": "There is no known person controlling this entity."}]  # fmt: skip
    assert [c["relationship"] for c in body["children"]["data"]] == ["direct", "ultimate_only"]
    subs = body["subsidiaries"]
    assert subs["total"] == 2 and subs["data"][0]["lei"] == KID and subs["data"][1]["lei"] is None
    assert subs["filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert "gleif.org" not in str(body) and "http" not in str(body["parents"])
