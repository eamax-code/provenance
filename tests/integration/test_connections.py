"""The connections graph and its list endpoints (GH #24, ADR 0011)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Filing
from app.services import insiders
from app.services.sec_client import filing_index_url

FIX = Path(__file__).parents[1] / "fixtures" / "connections"
TODAY = date.today()
AAPL = "0000320193"
MSFT = "0000789019"
EX21_2024 = """<table><tr><td>Name</td><td>Jurisdiction of Incorporation</td></tr>
<tr><td>Apple Asia Limited</td><td>Hong Kong</td></tr>
<tr><td>Braeburn Capital, Inc.</td><td>Nevada, U.S.</td></tr>
<tr><td>Microsoft Corp</td><td>Washington</td></tr></table>"""
EX21_2023 = """<table><tr><td>Apple Asia Limited</td><td>Hong Kong</td></tr>
<tr><td>Apple Sales Ireland</td><td>Ireland</td></tr></table>"""


def _index(cik: str, acc: str, kind: str, doc: str) -> str:
    base = f"/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    return (
        '<table><tr><td>1</td><td>10-K</td><td><a href="/ix?doc=' + base + '/main.htm">m</a></td>'
        "<td>10-K</td><td>1</td></tr>"
        f'<tr><td>2</td><td>{kind}</td><td><a href="{base}/{doc}">e</a></td><td>{kind}</td>'
        "<td>1</td></tr></table>"
    )


def _filing(db, cik, acc, form, filed, doc):
    db.add(
        Filing(
            cik=cik, accession_number=acc, form_type=form, filing_date=filed, primary_document=doc,
            source_url=filing_index_url(cik, acc), first_detected_at=datetime.now(UTC),
            quality_status="ok",
        )
    )  # fmt: skip


def _owner(acc, cik, name, filed, issuer=AAPL, **flags):
    return acc, {"issuer_cik": issuer, "form_type": "4", "filing_date": filed,
                 "period_of_report": filed, "plan_10b5_1": None}, {
        "accession_number": acc, "owner_cik": cik, "owner_name": name,
        "is_director": flags.get("director", False), "is_officer": flags.get("officer", False),
        "is_ten_percent_owner": flags.get("ten", False), "is_other": False,
        "officer_title": flags.get("title"), "other_text": None,
    }  # fmt: skip


def _tx(acc, key, code, shares, price, after, when, issuer=AAPL):
    return {"accession_number": acc, "row_kind": "transaction", "is_derivative": False,
            "row_key": key, "security_title": "Common Stock", "trans_date": when,
            "trans_code": code, "shares": Decimal(shares), "price": Decimal(price),
            "acquired_disposed": "D" if code == "S" else "A", "shares_after": Decimal(after),
            "direct_indirect": "D", "nature_of_ownership": None, "underlying_title": None,
            "underlying_shares": None, "exercise_price": None}  # fmt: skip


@pytest.fixture
def connected(db, sec_client, fake_sec, ingested_aapl):
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "789019")
    parsed = insiders.Parsed()
    for acc, filing, owner in (
        _owner("0001-26-000001", "0000000101", "COOK TIMOTHY D", TODAY - timedelta(days=40),
               officer=True, director=True, title="Chief Executive Officer"),
        _owner("0001-26-000002", "0000000101", "COOK TIMOTHY D", TODAY - timedelta(days=90),
               issuer=MSFT, director=True),
        _owner("0001-26-000003", "0000000103", "LEVINSON ARTHUR D", TODAY - timedelta(days=60),
               director=True),
        _owner("0001-19-000004", "0000000104", "OLDHAND PETER", date(2019, 5, 1), officer=True,
               title="SVP"),
        _owner("0001-26-000005", MSFT, "MICROSOFT CORP", TODAY - timedelta(days=20), ten=True),
    ):  # fmt: skip
        parsed.filings[acc] = filing
        parsed.owners.append(owner)
    parsed.rows += [
        _tx("0001-26-000001", "1", "S", "1000", "200", "50000", TODAY - timedelta(days=41)),
        _tx("0001-26-000003", "2", "P", "100", "150", "4100", TODAY - timedelta(days=61)),
        _tx("0001-26-000002", "3", "P", "10", "400", "10", TODAY - timedelta(days=91), MSFT),
    ]
    insiders.store(db, parsed, "dataset:test")
    # exhibit 21 of the two 10-Ks in the Apple fixture
    for acc, doc, body in (
        ("0000320193-24-000123", "ex21.htm", EX21_2024),
        ("0000320193-23-000106", "ex21-2023.htm", EX21_2023),
    ):
        fake_sec.add(filing_index_url(AAPL, acc), _index(AAPL, acc, "EX-21.1", doc))
        fake_sec.add(f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/{doc}",
                     body)  # fmt: skip
    # two 13G amendments by the same filer (8.1%, then 0%) and a 13D about another issuer
    for acc, days, fixture in (
        ("0000102909-25-000100", 400, "schedule13g.xml"),
        ("0000102909-26-000630", 30, "schedule13g_below.xml"),
        ("0000899140-26-001318", 10, "schedule13d.xml"),
    ):
        form = "SCHEDULE 13D" if "13d" in fixture else "SCHEDULE 13G/A"
        _filing(db, AAPL, acc, form, TODAY - timedelta(days=days),
                f"xsl{form.replace(' ', '_')[:11]}_X02/primary_doc.xml")  # fmt: skip
        fake_sec.add(f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/"
                     "primary_doc.xml", (FIX / fixture).read_text())  # fmt: skip
    # a Form 4 newer than the loaded data sets, read from its XML
    _filing(db, AAPL, "0001140361-26-043484", "4", TODAY - timedelta(days=5),
            "xslF345X06/form4.xml")  # fmt: skip
    fake_sec.add("https://www.sec.gov/Archives/edgar/data/320193/000114036126043484/form4.xml",
                 (FIX / "form4_aapl.xml").read_text())  # fmt: skip
    db.commit()
    return fake_sec


def test_demo_key_reads_stored_connections_without_reaching_the_sec(client, connected):
    before = len(connected.calls)
    r = client.get(f"/v1/companies/{AAPL}/graph?api_key=demo")
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["refreshing"] is False and len(connected.calls) == before
    labels = {n["label"] for n in g["nodes"]}
    assert {"Timothy D Cook", "Arthur D Levinson"} <= labels
    assert "Peter Oldhand" not in labels  # former insider
    assert g["sources"]["subsidiaries"]["count"] == 0  # not read yet


def test_a_keyed_request_reads_the_sources_then_serves_the_graph(client, auth, connected):
    first = client.get(f"/v1/companies/{AAPL}/graph", headers=auth).json()
    assert first["refreshing"] is True  # the read runs after the response
    r = client.get(f"/v1/companies/{AAPL}/graph?former=true", headers=auth)
    g = r.json()
    assert g["refreshing"] is False
    assert "data.sec.gov" not in r.text and "first_detected_at" not in r.text
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes[f"company:{AAPL}"]["group"] == "center"
    # insiders: people, a company that is a 10% owner, and the Form 4 read from its XML
    assert nodes["person:0000000101"]["label"] == "Timothy D Cook"
    assert nodes[f"company:{MSFT}"]["cik"] == MSFT
    assert nodes["person:0001780525"]["label"] == "Jennifer Newstead"
    by_type = {}
    for e in g["edges"]:
        by_type.setdefault(e["type"], []).append(e)
        assert e["evidence"]["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/")
    cook = next(e for e in by_type["officer"] if e["source"] == "person:0000000101")
    assert cook["label"] == "Chief Executive Officer, Director" and cook["current"] is True
    assert any(e["source"] == "person:0000000101" and e["target"] == f"company:{MSFT}"
               for e in by_type["interlock"])  # fmt: skip
    # subsidiaries: the 2024 exhibit, one of them a registrant here, new names flagged
    subs = [nodes[e["target"]] for e in by_type["subsidiary"]]
    assert {s["label"] for s in subs} >= {"Apple Asia Limited", "Braeburn Capital, Inc."}
    braeburn = next(s for s in subs if s["label"].startswith("Braeburn"))
    assert braeburn["detail"]["jurisdiction_group"] == "United States"
    assert braeburn["detail"]["new_this_year"] is True
    assert g["sources"]["subsidiaries"]["removed"] == ["Apple Sales Ireland"]
    # holders: the latest 13G is below 5%; the 13D about another issuer is ignored
    (holder,) = by_type["holder"]
    assert holder["current"] is False and holder["percent"] == 0
    assert holder["evidence"]["accession_number"] == "0000102909-26-000630"


def test_as_of_uses_only_filings_made_by_then(client, auth, connected):
    client.get(f"/v1/companies/{AAPL}/graph", headers=auth)  # read the sources
    when = (TODAY - timedelta(days=200)).isoformat()
    g = client.get(f"/v1/companies/{AAPL}/graph?as_of={when}", headers=auth).json()
    labels = {n["label"] for n in g["nodes"]}
    assert "Timothy D Cook" not in labels  # his only Apple filing came later
    (holder,) = [e for e in g["edges"] if e["type"] == "holder"]
    assert holder["percent"] == 8.1 and holder["current"] is True
    old = client.get(f"/v1/companies/{AAPL}/graph?as_of=2024-01-01&include=subsidiaries",
                     headers=auth).json()  # fmt: skip
    assert {n["label"] for n in old["nodes"] if n["group"] == "subsidiaries"} == {
        "Apple Asia Limited", "Apple Sales Ireland"
    }  # fmt: skip
    assert {e["type"] for e in old["edges"]} == {"subsidiary"}


def test_insiders_list(client, auth, connected):
    data = client.get(f"/v1/companies/{AAPL}/insiders", headers=auth).json()["data"]
    cook = next(i for i in data if i["owner_cik"] == "0000000101")
    assert cook["role"] == "Chief Executive Officer, Director" and cook["current"]
    assert cook["open_market_12m"] == {"bought_value": 0.0, "sold_value": 200000.0,
                                       "buys": 0, "sells": 1}  # fmt: skip
    assert cook["shares_held"] == 50000.0
    assert cook["other_companies"][0]["cik"] == MSFT
    assert cook["other_companies"][0]["role"] == "Director"
    assert cook["latest_filing"]["source_url"].endswith("0001-26-000001-index.html")
    ms = next(i for i in data if i["owner_cik"] == MSFT)
    assert ms["kind"] == "entity" and ms["company_cik"] == MSFT and ms["role"] == "10% owner"
    assert all(i["owner_cik"] != "0000000104" for i in data)
    everyone = client.get(f"/v1/companies/{AAPL}/insiders?former=true", headers=auth).json()
    assert any(i["owner_cik"] == "0000000104" and not i["current"] for i in everyone["data"])


def test_insider_transactions(client, auth, connected):
    r = client.get(f"/v1/companies/{AAPL}/insider-transactions?code=S,P", headers=auth).json()
    assert [t["trans_code"] for t in r["data"]] == ["S", "P"]
    sale = r["data"][0]
    assert sale["value"] == 200000.0 and sale["trans_code_label"] == "open-market sale"
    assert sale["owner_name"] == "Timothy D Cook" and sale["source_url"].startswith(
        "https://www.sec"
    )
    one = client.get(f"/v1/companies/{AAPL}/insider-transactions?limit=1", headers=auth).json()
    assert one["meta"]["has_more"] is True
    bad = client.get(f"/v1/companies/{AAPL}/insider-transactions?code=ZZ", headers=auth)
    assert bad.status_code == 422


def test_subsidiaries_and_holders_lists(client, auth, connected):
    client.get(f"/v1/companies/{AAPL}/subsidiaries", headers=auth)  # read the sources
    s = client.get(f"/v1/companies/{AAPL}/subsidiaries", headers=auth).json()
    assert s["exhibit"] == "EX-21.1" and s["filing"]["accession_number"] == "0000320193-24-000123"
    assert [x["name"] for x in s["data"] if x["new_this_year"]] == [
        "Braeburn Capital, Inc.", "Microsoft Corp"
    ]  # fmt: skip
    assert s["removed"] == ["Apple Sales Ireland"] and s["previous"]["count"] == 2
    assert client.get(f"/v1/companies/{AAPL}/holders", headers=auth).json()["data"] == []
    below = client.get(f"/v1/companies/{AAPL}/holders?below=true", headers=auth).json()["data"]
    assert below[0]["name"] == "The Vanguard Group" and below[0]["below_threshold"] is True
    assert below[0]["holder_type_label"] == "investment adviser"


def test_bad_layers_are_refused(client, auth, connected):
    r = client.get(f"/v1/companies/{AAPL}/graph?include=insiders,gossip", headers=auth)
    assert r.status_code == 422 and "gossip" in r.json()["error"]["message"]


def test_reloading_a_quarter_replaces_its_rows(db, connected):
    parsed = insiders.Parsed()
    acc, filing, owner = _owner("0001-26-000001", "0000000101", "COOK TIMOTHY D",
                                TODAY - timedelta(days=40), officer=True, title="CEO")  # fmt: skip
    parsed.filings[acc] = filing
    parsed.owners.append(owner)
    insiders.store(db, parsed, "dataset:test")
    db.commit()
    rows = [o for o in insiders.roles(db, AAPL) if o["owner_cik"] == "0000000101"]
    assert len(rows) == 1 and rows[0]["officer_title"] == "CEO" and rows[0]["filings"] == 1


def test_mcp_tools_reach_the_graph(client, connected):
    import json

    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"company_connections", "insider_transactions"} <= names
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "company_connections",
                       "arguments": {"cik": "320193", "include": "insiders"}}}  # fmt: skip
    res = client.post("/mcp", json=body).json()["result"]
    assert res["isError"] is False
    g = json.loads(res["content"][0]["text"])
    assert {e["type"] for e in g["edges"]} <= {"officer", "director", "ten_percent_owner"}
    assert any(n["label"] == "Timothy D Cook" for n in g["nodes"])


def test_a_holder_who_is_also_an_insider_is_one_node(db, client, auth, connected):
    from app.db.models import BeneficialOwner

    db.add(BeneficialOwner(subject_cik=AAPL, accession_number="0000000101-26-000001",
                           form_type="SCHEDULE 13G", filing_date=TODAY - timedelta(days=3),
                           filer_cik="0000000101", position=0, holder_name="Timothy D. Cook",
                           holder_cik="0000000101", holder_type="IN", percent=Decimal("6.2"),
                           source_url=filing_index_url(AAPL, "0000000101-26-000001")))  # fmt: skip
    db.commit()
    g = client.get(f"/v1/companies/{AAPL}/graph?api_key=demo").json()
    assert sum(1 for n in g["nodes"] if n["id"].endswith(":0000000101")) == 1
    types = {e["type"] for e in g["edges"] if e["source"] == "person:0000000101"}
    assert {"officer", "holder", "interlock"} <= types


def test_daily_job_loads_new_quarters_and_refreshes_the_showcase(db, settings, sec_client,
                                                                 connected, tmp_path):  # fmt: skip
    import zipfile

    from app.db.models import InsiderDataset, InsiderFiling
    from app.jobs import connections as job

    settings.sec_bulk_dir = str(tmp_path / "bulk")
    zpath = tmp_path / "q.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tPERIOD_OF_REPORT\t"
                    "DOCUMENT_TYPE\tISSUERCIK\tAFF10B5ONE\n"
                    "0009-26-000001\t01-AUG-2026\t30-JUL-2026\t4\t0000320193\t0\n")  # fmt: skip
        zf.writestr("REPORTINGOWNER.tsv", "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\t"
                    "RPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\tRPTOWNER_TXT\n"
                    "0009-26-000001\t0000000900\tNEWCOMER ANN\tDirector\t\t\n")  # fmt: skip
    connected.add(insiders.DATASETS_PAGE, '<a href="/files/x/2026q3_form345.zip">2026 Q3</a>')
    from app.services import fails_to_deliver

    connected.add(fails_to_deliver.PAGE, "<p>no new files</p>")  # Q-06: none published

    def handler(request):  # the zip is binary, so it is served here rather than by FakeSEC
        if str(request.url).endswith("2026q3_form345.zip"):
            return httpx.Response(200, content=zpath.read_bytes())
        return connected.handler(request)

    sec_client.http = httpx.Client(transport=httpx.MockTransport(handler))
    out = job.run(db, settings, sec_client)
    assert [d["quarter"] for d in out["datasets"]] == ["2026q3"] and out["errors"] == 0
    assert out["companies"] >= 1 and out["fails_to_deliver"]["files_to_load"] == 0
    assert db.get(InsiderDataset, "2026q3").filings == 1
    newcomer = select(InsiderFiling.owner_name).where(InsiderFiling.owner_cik == "0000000900")
    assert db.scalar(newcomer) == "NEWCOMER ANN"
    again = job.run(db, settings, sec_client)  # nothing newer: no download
    assert again["datasets"] == []
    assert job.maybe_run(db, settings, date(2026, 1, 1), date(2026, 1, 1)) == date(2026, 1, 1)
