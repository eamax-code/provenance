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


def _seed(db, exhibit21=True):
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
                                     ("Braeburn Capital, Inc.", "Nevada")) if exhibit21
                                    else ()):  # fmt: skip
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
    if exhibit21:
        db.add(SubsidiaryLei(subsidiary_id=100, lei=KID))
    db.commit()


def test_corporate_tree_endpoint(client, auth, db, ingested_aapl):
    _seed(db)
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


def _ask(client, auth, q):
    r = client.post("/v1/chat", json={"message": q, "cik": CIK}, headers=auth).json()
    assert r["intent"] == "corporate_tree" and r["answered_by"] == "data", r
    return r


def test_corporate_tree_chat_answer_with_a_table(client, auth, db, ingested_aapl):
    """C-16: parents as reported to GLEIF (named, never linked), the GLEIF children and the
    latest exhibit 21, cited to its filing, with the existing table block."""
    from app.services.chat_intents import detect

    for q in (
        "What is Apple's parent company?",
        "List Apple's subsidiaries",
        "Who is the ultimate parent of Apple?",
        "Show Apple's corporate structure",
    ):
        assert detect(q) == "corporate_tree", q
    assert detect("What is Apple's LEI?") == "lei" and detect("Who owns Apple?") == "holders"
    _seed(db)
    r = _ask(client, auth, "What is Apple's parent company?")
    a = r["answer"]
    assert a.startswith("GLEIF lists Apple Inc.'s direct parent as Parent Holdings Ltd (GB).")
    assert "For its ultimate parent, Apple Inc. reports to GLEIF: There is no known person " \
        "controlling this entity." in a  # fmt: skip
    assert "2 entities report Apple Inc. as their parent to GLEIF (1 as direct parent)." in a
    assert "Its latest exhibit 21, in the 10-K filed 2025-10-31, lists 2 subsidiaries (1 " \
        "matched to an LEI by exact name and jurisdiction) [" in a  # fmt: skip
    assert [c["url"] for c in r["citations"] if c["url"] and "ex21" in c["url"]] == [
        "https://www.sec.gov/Archives/edgar/data/320193/x/ex21.htm"]  # fmt: skip
    assert "gleif.org" not in str(r)
    table = next(b for b in r["blocks"] if b["type"] == "table")
    assert table["title"] == "Exhibit 21 subsidiaries, Apple Inc."
    assert table["rows"][0] == [
        {"text": "Apple Operations Limited",
         "url": "https://www.sec.gov/Archives/edgar/data/320193/x/ex21.htm"},
        {"text": "Ireland"}, {"text": KID}]  # fmt: skip
    assert table["rows"][1][2] == {"text": "—"}


def test_corporate_tree_chat_without_an_exhibit_21_shows_the_gleif_children(
    client, auth, db, ingested_aapl
):
    _seed(db, exhibit21=False)
    db.add(GleifException(lei=ME, kind="direct", reason="NO_KNOWN_PERSON"))
    db.query(GleifRelationship).filter_by(child_lei=ME).delete()
    db.commit()
    r = _ask(client, auth, "List Apple's subsidiaries")
    assert r["answer"].startswith(
        "For its direct and ultimate parents, Apple Inc. reports "
        "to GLEIF: There is no known person controlling this entity."
    )
    assert r["answer"].count("no known person") == 1
    assert "No exhibit 21 subsidiary list for Apple Inc. is in the filings loaded here" in \
        r["answer"]  # fmt: skip
    table = next(b for b in r["blocks"] if b["type"] == "table")
    assert table["title"] == "Entities reporting Apple Inc. as parent (GLEIF)"
    assert [row[2]["text"] for row in table["rows"]] == ["direct", "ultimate only"]
    assert all("url" not in cell for row in table["rows"] for cell in row)  # GLEIF: not linked
