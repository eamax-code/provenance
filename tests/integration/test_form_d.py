"""D-15: private raises from Form D (docs/contracts/private-raises.md)."""

from __future__ import annotations

import re
import zipfile
from datetime import date

from app.services import conversation, form_d

CIK = "0000320193"
HEAD = {
    "FORMDSUBMISSION": ["ACCESSIONNUMBER", "FILE_NUM", "FILING_DATE", "SIC_CODE", "SCHEMAVERSION",
                        "SUBMISSIONTYPE", "TESTORLIVE"],
    "ISSUERS": ["ACCESSIONNUMBER", "IS_PRIMARYISSUER_FLAG", "CIK", "ENTITYNAME",
                "STATEORCOUNTRY", "JURISDICTIONOFINC", "ENTITYTYPE", "YEAROFINC_VALUE_ENTERED"],
    "OFFERING": ["ACCESSIONNUMBER", "INDUSTRYGROUPTYPE", "FEDERALEXEMPTIONS_ITEMS_LIST",
                 "SALE_DATE", "YETTOOCCUR", "MINIMUMINVESTMENTACCEPTED", "TOTALOFFERINGAMOUNT",
                 "TOTALAMOUNTSOLD", "TOTALREMAINING", "NUMBERNONACCREDITEDINVESTORS",
                 "TOTALNUMBERALREADYINVESTED", "SALESCOMM_DOLLARAMOUNT",
                 "FINDERSFEE_DOLLARAMOUNT"],
    "RELATEDPERSONS": ["ACCESSIONNUMBER", "FIRSTNAME", "MIDDLENAME", "LASTNAME", "CITY",
                       "STATEORCOUNTRY", "RELATIONSHIP_1", "RELATIONSHIP_2", "RELATIONSHIP_3"],
}  # fmt: skip
ROWS = {
    "FORMDSUBMISSION": [
        ["0001-26-000001", "021-1", "03-AUG-2026", "", "X", "D", "LIVE"],
        ["0001-26-000002", "021-1", "20-SEP-2026", "", "X", "D/A", "LIVE"],
        ["0002-26-000001", "021-2", "10-SEP-2026", "", "X", "D", "LIVE"],
        ["0003-26-000001", "021-3", "11-SEP-2026", "", "X", "D", "TEST"],  # a test filing
    ],
    "ISSUERS": [
        ["0001-26-000001", "YES", "320193", "Example Bio, Inc.", "CA", "DELAWARE",
         "Corporation", "2019"],
        ["0001-26-000002", "YES", "320193", "Example Bio, Inc.", "CA", "DELAWARE",
         "Corporation", "2019"],
        ["0002-26-000001", "YES", "0000999001", "Big Fund LP", "NY", "DELAWARE",
         "Limited Partnership", "2025"],
        ["0003-26-000001", "YES", "0000999002", "Test Co", "NY", "DELAWARE", "Corporation", ""],
    ],
    "OFFERING": [
        ["0001-26-000001", "Biotechnology", "06b", "2026-07-30", "false", "0", "60000000",
         "20000000", "40000000", "0", "8", "0", "0"],
        ["0001-26-000002", "Biotechnology", "06b", "2026-07-30", "false", "0", "60000000",
         "55000000", "5000000", "0", "14", "0", "0"],
        ["0002-26-000001", "Pooled Investment Fund", "06b,3C,3C.7", "", "true", "250000",
         "Indefinite", "0", "Indefinite", "0", "0", "0", "0"],
        ["0003-26-000001", "Other", "06b", "", "true", "0", "5", "0", "5", "0", "0", "0", "0"],
    ],
    "RELATEDPERSONS": [["0001-26-000002", "Jane", "", "Doe", "San Francisco", "CA",
                        "Executive Officer", "Director", ""]],
}  # fmt: skip


def _zip(tmp_path):
    p = tmp_path / "2026q3_d.zip"
    with zipfile.ZipFile(p, "w") as z:
        for name, cols in HEAD.items():
            body = "\t".join(cols) + "\n" + "".join("\t".join(r) + "\n" for r in ROWS[name])
            z.writestr(f"2026Q3_d/{name}.tsv", body)
    return p


def test_load_chains_amendments_and_serves_offerings(tmp_path, db, client, auth, ingested_aapl):
    stats = form_d.load(db, [_zip(tmp_path)])
    assert stats == {"filings": 3, "offerings": 2}  # the TEST filing is skipped
    body = client.get(f"/v1/companies/{CIK}/private-raises", headers=auth).json()
    assert body["labels"]["basis"] == "Self-reported by the issuer on Form D; amounts as filed."
    (o,) = body["data"]
    assert o["latest_filing"]["form"] == "D/A" and len(o["filings"]) == 2
    assert (o["total_offering_amount"], o["total_amount_sold"]) == (60000000, 55000000)
    assert o["investors"] == {"total": 14, "non_accredited": 0}
    assert o["related_persons"][0]["name"] == "Jane Doe" and o["exemptions"] == ["06b"]
    assert o["latest_filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    lst = client.get("/v1/private-raises?industry=biotechnology&min_amount=50000000",
                     headers=auth).json()  # fmt: skip
    assert [x["issuer"]["name"] for x in lst["data"]] == ["Example Bio, Inc."]
    fund = client.get("/v1/private-raises?exemption=3C.7", headers=auth).json()["data"]
    assert fund[0]["indefinite"] and fund[0]["total_offering_amount"] is None
    assert client.get("/v1/private-raises?from=2026-10-01&to=2026-09-01",
                      headers=auth).status_code == 422  # fmt: skip


def test_chat_plans_private_raises():
    today = date(2026, 11, 24)
    p = conversation.plan("Who raised over $50M in biotech last quarter?", None)
    assert p.kind == "private_raises"
    f = conversation.private_raise_filters("Who raised over $50M in biotech last quarter?", today)
    assert f["min_amount"] == 50e6 and f["industry"] == "Biotechnology"
    assert (f["start"], f["end"]) == (date(2026, 7, 1), date(2026, 9, 30))
    assert conversation.plan("Which companies raised revenue guidance?", None) is None
    assert conversation.plan("Did Apple raise its dividend?", None) is None


def test_raised_means_amount_sold_once_per_offering(tmp_path, db):
    """'Raised' is the amount sold on the latest filing (cumulative), never the offering size;
    an amended offering counts once."""
    form_d.load(db, [_zip(tmp_path)])
    today = date(2026, 11, 24)
    p = conversation.plan("Who raised over $50M in biotech last quarter?", None)
    a = conversation.answer(db, p, None, today)
    assert "Example Bio, Inc., $55.0 million sold (offering size $60.0 million)" in a.answer
    assert a.answer.count("Example Bio") == 1 and a.answer.startswith("1 issuer reported")
    none = conversation.answer(db, conversation.plan(
        "Who raised over $56M in biotech last quarter?", None), None, today)  # fmt: skip
    assert none.answer.startswith("No Form D notice")  # a $60M offering size does not count
    fund, _ = form_d.search(db, exemption="3C.7")
    assert fund[0]["total_offering_amount"] is None and fund[0]["indefinite"]  # never 0


def test_implausible_amounts_are_flagged_and_left_out_of_rankings(tmp_path, db, client, auth):
    """D-15b: $100B or more is suspect unless the issuer is a cash-management vehicle."""
    assert form_d.quality_of("LOWE INTERNATIONAL HOLDING CO", 999_999_750_000, 999_999_750_000) \
        == "suspect_amount"  # fmt: skip
    assert form_d.quality_of("Western Asset Institutional Cash Reserves", None, 184e9) == "ok"
    assert form_d.quality_of("X.AI Holdings Corp.", 19_999_999_972, 16_599_961_030) == "ok"
    form_d.load(db, [_zip(tmp_path)])
    from app.db.models import FormDFiling

    big = db.get(FormDFiling, "0002-26-000001")  # make the fund's figure implausible
    big.issuer_name, big.total_amount_sold = "Big Fund LP", 900e9
    form_d.mark_quality(db)
    db.commit()
    ranked = client.get("/v1/private-raises?order=sold", headers=auth).json()["data"]
    assert "Big Fund LP" not in [x["issuer"]["name"] for x in ranked]
    every = client.get("/v1/private-raises?order=sold&include_suspect=true",
                       headers=auth).json()["data"]  # fmt: skip
    assert every[0]["issuer"]["name"] == "Big Fund LP"
    assert every[0]["quality_status"] == "suspect_amount" and every[0]["total_amount_sold"] == 9e11
    assert client.get("/v1/private-raises", headers=auth).json()["data"]  # by date: all listed
    no_funds = client.get("/v1/private-raises?exclude_industry=Pooled%20Investment%20Fund",
                          headers=auth).json()["data"]  # fmt: skip
    assert [x["issuer"]["name"] for x in no_funds] == ["Example Bio, Inc."]


def test_ask_links_quote_an_accession_and_get_that_offering(tmp_path, db, client, auth,
                                                            ingested_aapl):  # fmt: skip
    """2026-11-24 (provenance-ui): every Form D Ask link quotes the offering's accession number.
    With the issuer's cik it was answered with a company summary; without one (most Form D
    issuers file nothing else) it got the 90-day list. It now answers that one offering, as filed
    and cited, under no company unless the offering is the given company's own."""
    p = _zip(tmp_path)
    with zipfile.ZipFile(p) as z:  # full-length accession numbers, as on EDGAR
        files = {n: re.sub(r"(?m)^000(\d)-26-", r"000000000\1-26-", z.read(n).decode())
                 for n in z.namelist()}  # fmt: skip
    with zipfile.ZipFile(p, "w") as z:
        for n, body in files.items():
            z.writestr(n, body)
    form_d.load(db, [p])

    def ask(message, cik=None):
        body = {"message": message, **({"cik": cik} if cik else {})}
        return client.post("/v1/chat", json=body, headers=auth).json()

    r = ask(
        "Tell me about the Form D offering filed 2026-09-20 (accession 0000000001-26-000002): "
        "how much was raised, from how many investors, under which exemption?",
        "320193",
    )
    assert r["intent"] == "private_raises" and r["company"]["cik"] == CIK
    assert "$60.0 million offered, $55.0 million sold" in r["answer"]
    assert "14 investors so far, all accredited" in r["answer"] and "Rule 506(b)" in r["answer"]
    assert "Jane Doe (Executive Officer, Director)" in r["answer"]
    from app.db.models import FormDFiling

    db.get(FormDFiling, "0000000001-26-000002").investors_non_accredited = None  # left blank
    db.commit()
    blank = ask("Form D offering (accession 0000000001-26-000002)", "320193")["answer"]
    assert "14 investors so far." in blank and "accredited" not in blank
    assert r["answer"].endswith(form_d.BASIS)
    old = ask("Tell me about the Form D offering filed 2026-08-03 (accession 0000000001-26-000001)",
              "320193")  # fmt: skip
    assert "is an earlier filing of this offering" in old["answer"]
    fund = ask("Tell me about Big Fund LP's Form D offering filed 2026-09-10 "
               "(accession 0000000002-26-000001).")  # fmt: skip
    assert fund["company"] is None and fund["intent"] == "private_raises"
    assert "an indefinite amount offered" in fund["answer"] and "No investors yet" in fund["answer"]
    assert [c["url"] for c in fund["citations"]] == [
        "https://www.sec.gov/Archives/edgar/data/999001/000000000226000001/0000000002-26-000001-index.html"
    ]
    other = ask("Tell me about the Form D offering (accession 0000000002-26-000001)", "320193")
    assert other["company"] is None and "Big Fund LP" in other["answer"]  # not Apple's
    # the issuer files with us (Example Bio is under Apple's CIK here): answered under it even
    # when the Ask link carries no cik (2026-11-24, provenance-ui: WeShop came back under none)
    own = ask("Tell me about Example Bio, Inc.’s Form D offering filed 2026-09-20 "
              "(accession 0000000001-26-000002).")  # fmt: skip
    assert own["company"]["cik"] == CIK and own["intent"] == "private_raises"
    assert "$55.0 million sold" in own["answer"]
    missing = ask("Tell me about Nobody's Form D offering (accession 0009999999-26-000009).")
    assert missing["answer"].startswith("No Form D with accession number 0009999999-26-000009")
