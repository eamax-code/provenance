"""Q-02: issuer names as filed on Forms 13F (the name most managers give a security a quarter)."""

from __future__ import annotations

from datetime import date

from app.services import thirteenf

GOOD = "037833100"  # a valid CUSIP (check digit), internal only


def _submission(rows: str) -> str:
    return ("<DOCUMENT>\n<TYPE>INFORMATION TABLE\n<TEXT>\n<XML>\n"
            "<informationTable xmlns=\"http://www.sec.gov/edgar/document/thirteenf/informationtable\">"
            + rows + "</informationTable>\n</XML>\n</TEXT>\n</DOCUMENT>")  # fmt: skip


def _info(name: str, cusip: str = GOOD, kind: str = "SH", putcall: str = "") -> str:
    pc = f"<putCall>{putcall}</putCall>" if putcall else ""
    return (f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><cusip>{cusip}</cusip>"
            f"<shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>{kind}</sshPrnamtType>"
            f"</shrsOrPrnAmt>{pc}</infoTable>")  # fmt: skip


def test_the_name_most_managers_give_one_vote_per_filing():
    q = date(2026, 9, 30)
    out: dict = {}
    # filing A lists the security twice (two discretion rows): one vote
    thirteenf.names_from_submission(_submission(_info("APPLE INC") + _info("APPLE INC")), "A", q,
                                    out)  # fmt: skip
    thirteenf.names_from_submission(_submission(_info("Apple  Inc")), "B", q, out)
    thirteenf.names_from_submission(_submission(_info("APPLE COMPUTER")), "C", q, out)
    # put/call rows and principal amounts are not shares: no vote
    options = _info("WRONG", putcall="Put") + _info("WRONG", kind="PRN")
    thirteenf.names_from_submission(_submission(options), "D", q, out)
    (row,) = thirteenf.name_rows(out)
    assert (row["name"], row["managers"], row["share"]) == ("APPLE INC", 3, 0.6667)
    assert row["cusip"] == GOOD and row["report_period"] == q


def test_a_notice_names_the_managers_that_report_for_it():
    text = ("<DOCUMENT>\n<TYPE>13F-NT\n<TEXT>\n<XML>\n<edgarSubmission xmlns=\"http://www.sec.gov/"
            "edgar/thirteenffiler\"><formData><coverPage><otherManagersInfo>"
            "<otherManager><cik>0002100121</cik><form13FFileNumber>028-26877</form13FFileNumber>"
            "<name>VANGUARD PORTFOLIO MANAGEMENT LLC</name></otherManager>"
            "<otherManager><form13FFileNumber>028-11111</form13FFileNumber>"
            "<name>An  Adviser Ltd</name></otherManager>"
            "</otherManagersInfo></coverPage></formData></edgarSubmission>\n</XML>\n</TEXT>\n"
            "</DOCUMENT>")  # fmt: skip
    rows = thirteenf.reported_by_from_submission(text, "0000102909-26-002727")
    assert [(r["seq"], r["cik"], r["file_number"], r["name"]) for r in rows] == [
        (1, "0002100121", "028-26877", "VANGUARD PORTFOLIO MANAGEMENT LLC"),
        (2, None, "028-11111", "An Adviser Ltd")]  # fmt: skip
