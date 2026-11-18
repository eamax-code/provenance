"""Parsers behind the connections graph: insider data sets and Form 4 XML, exhibit 21, and
Schedules 13D/13G (ADR 0011). Fixtures are trimmed copies of real EDGAR documents."""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import beneficial_owners, insiders, subsidiaries

FIX = Path(__file__).parents[1] / "fixtures" / "connections"

SUBMISSION = (
    "ACCESSION_NUMBER\tFILING_DATE\tPERIOD_OF_REPORT\tDATE_OF_ORIG_SUB\tNO_SECURITIES_OWNED\t"
    "NOT_SUBJECT_SEC16\tFORM3_HOLDINGS_REPORTED\tFORM4_TRANS_REPORTED\tDOCUMENT_TYPE\tISSUERCIK\t"
    "ISSUERNAME\tISSUERTRADINGSYMBOL\tREMARKS\tAFF10B5ONE\n"
    "0001-25-000001\t31-JUL-2025\t30-JUL-2025\t\t\t0\t\t\t4\t0000320193\tApple Inc.\tAAPL\t\t1\n"
    "0001-25-000002\t01-AUG-2025\t30-JUL-2025\t\t\t0\t\t\t4/A\t320193\tApple Inc.\tAAPL\t\t0\n"
    "0001-25-000003\t01-AUG-2025\t30-JUL-2025\t\t\t0\t\t\t4\t0000789019\tMicrosoft\tMSFT\t\t\n"
    "0001-25-000004\t01-AUG-2025\t30-JUL-2025\t\t\t0\t\t\tD\t0000320193\tApple Inc.\tAAPL\t\t\n"
)
OWNERS = (
    "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\t"
    "RPTOWNER_TXT\tRPTOWNER_STREET1\tRPTOWNER_STREET2\tRPTOWNER_CITY\tRPTOWNER_STATE\t"
    "RPTOWNER_ZIPCODE\tRPTOWNER_STATE_DESC\tFILE_NUMBER\n"
    "0001-25-000001\t0000000101\tCOOK TIMOTHY D\tDirector,Officer\tCEO\t\t1 HOME ST\t"
    "\tX\tCA\t1\t\t\n"
    "0001-25-000001\t0000000101\tCOOK TIMOTHY D\tDirector,Officer\tCEO\t\t1 HOME ST\t"
    "\tX\tCA\t1\t\t\n"
    "0001-25-000002\t0000000102\tBIG FUND LP\tTenPercentOwner\t\t\t2 FUND ST\t\tY\tNY\t2\t\t\n"
    "0001-25-000003\t0000000101\tCOOK TIMOTHY D\tDirector\t\t\t1 HOME ST\t\tX\tCA\t1\t\t\n"
)
TRANS = (
    "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tSECURITY_TITLE\tSECURITY_TITLE_FN\tTRANS_DATE\t"
    "TRANS_DATE_FN\tDEEMED_EXECUTION_DATE\tDEEMED_EXECUTION_DATE_FN\tTRANS_FORM_TYPE\tTRANS_CODE\t"
    "EQUITY_SWAP_INVOLVED\tEQUITY_SWAP_TRANS_CD_FN\tTRANS_TIMELINESS\tTRANS_TIMELINESS_FN\t"
    "TRANS_SHARES\tTRANS_SHARES_FN\tTRANS_PRICEPERSHARE\tTRANS_PRICEPERSHARE_FN\t"
    "TRANS_ACQUIRED_DISP_CD\tTRANS_ACQUIRED_DISP_CD_FN\tSHRS_OWND_FOLWNG_TRANS\t"
    "SHRS_OWND_FOLWNG_TRANS_FN\tVALU_OWND_FOLWNG_TRANS\tVALU_OWND_FOLWNG_TRANS_FN\t"
    "DIRECT_INDIRECT_OWNERSHIP\tDIRECT_INDIRECT_OWNERSHIP_FN\tNATURE_OF_OWNERSHIP\t"
    "NATURE_OF_OWNERSHIP_FN\n"
    "0001-25-000001\t11\tCommon Stock\t\t29-JUL-2025\t\t\t\t4\tS\t0\t\t\t\t5611.0\t\t94.8\t\tD\t\t"
    "3433.0\t\t\t\tD\t\t\t\n"
    "0001-25-000003\t12\tCommon Stock\t\t29-JUL-2025\t\t\t\t4\tP\t0\t\t\t\t10\t\t1\t\tA\t\t"
    "10\t\t\t\tD\t\t\t\n"
)


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "2025q3_form345.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SUBMISSION.tsv", SUBMISSION)
        zf.writestr("REPORTINGOWNER.tsv", OWNERS)
        zf.writestr("NONDERIV_TRANS.tsv", TRANS)
    return path


def test_dataset_keeps_owner_roles_and_rows_but_never_addresses(dataset):
    p = insiders.parse_dataset(dataset)
    assert set(p.filings) == {"0001-25-000001", "0001-25-000002", "0001-25-000003"}
    assert p.filings["0001-25-000002"]["issuer_cik"] == "0000320193"  # zero-padded
    assert p.filings["0001-25-000001"]["plan_10b5_1"] is True
    assert len(p.owners) == 3  # the duplicate owner line is dropped
    cook = p.owners[0]
    assert cook["is_director"] and cook["is_officer"] and cook["officer_title"] == "CEO"
    assert not any("HOME" in str(v) for o in p.owners for v in o.values())
    sale = p.rows[0]
    assert (sale["trans_code"], sale["shares"], sale["price"], sale["shares_after"]) == (
        "S", Decimal("5611.0"), Decimal("94.8"), Decimal("3433.0")
    )  # fmt: skip
    assert sale["trans_date"] == date(2025, 7, 29)
    only_apple = insiders.parse_dataset(dataset, issuers={"0000320193"})
    assert set(only_apple.filings) == {"0001-25-000001", "0001-25-000002"}


def test_form4_xml_has_the_same_shape():
    text = (FIX / "form4_aapl.xml").read_text()
    p = insiders.parse_ownership_xml(text, "0001140361-26-043484", date(2026, 11, 12))
    f = p.filings["0001140361-26-043484"]
    assert f["issuer_cik"] == "0000320193" and f["form_type"] == "4" and f["plan_10b5_1"] is True
    (o,) = p.owners
    assert o["owner_name"] == "Newstead Jennifer" and o["is_officer"] and not o["is_director"]
    assert o["officer_title"] == "SVP, GC and Government Affairs"
    (r,) = p.rows
    assert r["trans_code"] == "S" and r["shares"] == Decimal("2399") and r["shares_after"]


def test_xml_with_entities_is_refused():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ownershipDocument/>'
    with pytest.raises(ValueError):
        insiders.parse_ownership_xml(bomb, "x", date(2026, 1, 1))


@pytest.mark.parametrize(
    "filed,shown",
    [
        ("COOK TIMOTHY D", "Timothy D Cook"),
        ("O'BRIEN DEIRDRE", "Deirdre O'Brien"),
        ("MCDONALD ROBERT A", "Robert A McDonald"),
        ("Newstead Jennifer", "Jennifer Newstead"),
        ("BERKSHIRE HATHAWAY INC", "BERKSHIRE HATHAWAY INC"),
        ("Vanguard Group Inc", "Vanguard Group Inc"),
    ],
)
def test_display_name(filed, shown):
    assert insiders.display_name(filed) == shown


def test_role_label():
    base = dict(is_director=False, is_officer=False, is_ten_percent_owner=False, is_other=False,
                officer_title=None, other_text=None)  # fmt: skip
    assert insiders.role_label({**base, "is_officer": True, "officer_title": "CFO",
                                "is_director": True}) == "CFO, Director"  # fmt: skip
    assert insiders.role_label({**base, "is_ten_percent_owner": True}) == "10% owner"
    assert insiders.role_label({**base, "is_other": True, "other_text": "Former CEO"}) == (
        "Former CEO"
    )


EXHIBIT_TABLE = """
<p>Exhibit 21.1</p><p>Subsidiaries of Apple Inc.*</p>
<table>
<tr><td></td><td>Jurisdiction<br/>of Incorporation</td></tr>
<tr><td>Apple Asia Limited</td><td>Hong Kong</td></tr>
<tr><td>Apple Asia LLC</td><td>Delaware, U.S.</td><td>100%</td></tr>
<tr><td>Apple Operations International Limited</td><td>Ireland</td></tr>
<tr><td>Japan</td><td>iTunes K.K.</td></tr>
<tr><td>Apple Asia Limited</td><td>Hong Kong</td></tr>
</table><p>* Pursuant to Item 601(b)(21)(ii) of Regulation S-K, the names of other subsidiaries
are omitted.</p>
"""


def test_exhibit_table():
    assert subsidiaries.parse_exhibit(EXHIBIT_TABLE) == [
        ("Apple Asia Limited", "Hong Kong"),
        ("Apple Asia LLC", "Delaware, U.S."),
        ("Apple Operations International Limited", "Ireland"),
        ("iTunes K.K.", "Japan"),
    ]


def test_exhibit_lines():
    doc = (
        "<p>EXHIBIT 21</p><p>SUBSIDIARIES OF THE REGISTRANT</p><p>Foo Holdings LLC (Delaware)</p>"
        "<p>Bar Ltd. ........ Ireland</p><p>Baz GmbH, Germany</p>"
        "<p>Qux Inc., a Texas corporation</p><p>Widget Co (formerly Gadget Co)</p>"
    )
    assert subsidiaries.parse_exhibit(doc) == [
        ("Foo Holdings LLC", "Delaware"),
        ("Bar Ltd.", "Ireland"),
        ("Baz GmbH", "Germany"),
        ("Qux Inc.", "Texas"),
        ("Widget Co (formerly Gadget Co)", None),
    ]


def test_find_exhibit_in_the_filing_index():
    row = (
        '<tr><td scope="row">{n}</td><td scope="row">{t}</td><td scope="row"><a href="{h}">x</a>'
        '</td><td scope="row">{t}</td><td scope="row">1</td></tr>'
    )
    page = "<table>" + "".join(
        row.format(n=i, t=t, h=h)
        for i, (t, h) in enumerate(
            [
                ("10-K", "/ix?doc=/Archives/edgar/data/1/2/main.htm"),
                ("EX-10.1", "/Archives/edgar/data/1/2/ex10.htm"),
                ("EX-21.1", "/Archives/edgar/data/1/2/ex21.htm"),
            ]
        )
    ) + "</table>"  # fmt: skip
    assert subsidiaries.find_exhibit(page) == ("EX-21.1", "/Archives/edgar/data/1/2/ex21.htm")
    assert subsidiaries.find_exhibit("<table></table>") is None


@pytest.mark.parametrize(
    "place,group",
    [
        ("Delaware, U.S.", "United States"),
        ("Nevada", "United States"),
        ("England and Wales", "United Kingdom"),
        ("The Netherlands", "Netherlands"),
        ("Cayman Islands", "Cayman Islands"),
        (None, "Not stated"),
        ("Atlantis", "Atlantis"),
    ],
)
def test_jurisdiction_group(place, group):
    assert subsidiaries.jurisdiction_group(place) == group


def test_schedule_13g_and_13d():
    g = beneficial_owners.parse_schedule_xml((FIX / "schedule13g.xml").read_text())
    assert g["filer_cik"] == "0000102909" and g["issuer_cik"] == "0000320193"
    assert g["event_date"] == date(2026, 3, 13)
    assert g["persons"] == [
        {
            "name": "The Vanguard Group",
            "cik": None,
            "type": "IA",
            "shares": Decimal("1234567890"),
            "percent": Decimal("8.1"),
        }  # fmt: skip
    ]
    d = beneficial_owners.parse_schedule_xml((FIX / "schedule13d.xml").read_text())
    assert d["issuer_cik"] == "0000939930"
    assert [(p["name"], p["percent"]) for p in d["persons"]] == [
        ("INTERMARKET CORP/NY", Decimal("3.8")),
        ("David B. Forer", Decimal("4.6")),
        ("Thomas P. Borger", Decimal("3.8")),
    ]
    assert d["persons"][0]["cik"] == "0001034611"


def test_exhibit_title_block_is_not_a_subsidiary():
    doc = (
        "<p>EX-21.1</p><p>meta-12312025x10kexhibit211.htm</p><p>META PLATFORMS, INC.</p>"
        "<p>SUBSIDIARIES OF THE REGISTRANT</p><p>Facebook Holdings, LLC (Delaware)</p>"
        "<p>Instagram, LLC (Delaware)</p><p>Meta Platforms Ireland Limited (Ireland)</p>"
    )
    assert [n for n, _ in subsidiaries.parse_exhibit(doc)] == [
        "Facebook Holdings, LLC", "Instagram, LLC", "Meta Platforms Ireland Limited"
    ]  # fmt: skip


def test_exhibit_layout_quirks():
    rows = "".join(
        f"<tr>{''.join(f'<td>{c}</td>' for c in r)}</tr>"
        for r in [
            ["1.", "CISG Holdings Ltd. (2)", "BVI"],
            ["2.", "BWWS Limited", "Hong Kong SAR"],
            ["Insurance Agencies and Brokers"],
            ["3.", "Fanhua Lianxing Insurance Sales Co., Ltd.", "PRC"],
            ["Blockchain.tv", "Inc.", "Delaware"],
            ["Beasley Media Group, LLC", "(DE)"],
            ["30A Greenway Hotel, LLC", "​FL"],
        ]
    )
    got = subsidiaries.parse_exhibit(f"<table>{rows}</table>")
    assert got == [
        ("CISG Holdings Ltd.", "BVI"),
        ("BWWS Limited", "Hong Kong SAR"),
        ("Fanhua Lianxing Insurance Sales Co., Ltd.", "PRC"),
        ("Blockchain.tv, Inc.", "Delaware"),
        ("Beasley Media Group, LLC", "(DE)"),
        ("30A Greenway Hotel, LLC", "FL"),
    ]
    assert [subsidiaries.jurisdiction_group(p) for _, p in got] == [
        "British Virgin Islands", "Hong Kong", "China", "United States", "United States",
        "United States",
    ]  # fmt: skip
    assert subsidiaries.parse_exhibit("<p>Exhibit 21</p><p>None.</p>") == []
    split = "<p>KULR Technology Corporation</p><p>Delaware</p><p>KULR Ltd.</p><p>Japan</p>"
    assert subsidiaries.parse_exhibit(split) == [
        ("KULR Technology Corporation", "Delaware"), ("KULR Ltd.", "Japan")
    ]  # fmt: skip
