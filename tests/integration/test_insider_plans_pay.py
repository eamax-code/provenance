"""D-10 executive pay, D-11 trading plans, D-12 Form 144 (docs/contracts/)."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from decimal import Decimal

from app.db.models import (
    Form144Notice,
    InsiderFiling,
    InsiderTransaction,
    ProxyPayFact,
    TradingPlan,
)
from app.services import ecd, executive_pay, form144, insider_plans

CIK = "0000320193"

SUB = ["adsh", "cik", "name", "form", "period", "filed"]
NUM = ["adsh", "tag", "version", "ddate", "qtrs", "uom", "dimh", "iprx", "value", "footnote",
       "footlen", "dimn", "coreg", "durp", "datp", "dcml"]  # fmt: skip
TXT = [
    "adsh",
    "tag",
    "version",
    "ddate",
    "qtrs",
    "iprx",
    "lang",
    "dcml",
    "durp",
    "datp",
    "dimh",
    "dimn",
    "coreg",
    "escaped",
    "srclen",
    "txtlen",
    "footnote",
    "footlen",
    "context",
    "value",
]


def _tsv(cols, rows):
    return "\t".join(cols) + "\n" + "".join("\t".join(str(r.get(c, "")) for c in cols) + "\n"
                                            for r in rows)  # fmt: skip


def _zip(tmp_path, subs, nums, txts, dims):
    p = tmp_path / "2026_01_notes.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("sub.tsv", _tsv(SUB, subs))
        z.writestr("num.tsv", _tsv(NUM, nums))
        z.writestr("txt.tsv", _tsv(TXT, txts))
        z.writestr("dim.tsv", "dimhash\tsegments\tsegt\n" + "".join(
            f"{h}\t{s}\t0\n" for h, s in dims.items()))  # fmt: skip
    return p


def _t(adsh, tag, value, dimh="0x0", ddate="20251231", version="ecd/2024"):
    return {
        "adsh": adsh,
        "tag": tag,
        "version": version,
        "ddate": ddate,
        "qtrs": "1",
        "dimh": dimh,
        "value": value,
    }


def test_parse_date_takes_one_unambiguous_date():
    p = ecd.parse_date
    assert p("November 24, 2025") == date(2025, 11, 24)
    assert p("On May 7, 2024") == date(2024, 5, 7)
    assert p("Adoption (November 12, 2025)") == date(2025, 11, 12)
    assert p("6-Sep-23") == date(2023, 9, 6)
    assert p("9/6/2024(3)") == date(2024, 9, 6)
    assert p("December10, 2025") == date(2025, 12, 10)
    for vague in ("June 2023", "Adoption", "September 22, 2025 and September 21, 2026",
                  "Decision 5, 2024", "P252D", None):  # fmt: skip
        assert p(vague) is None
    assert ecd.parse_duration_days("P403D") == 403 and ecd.parse_duration_days("text") is None


def test_plan_rules_from_the_hand_check(tmp_path):
    q = "0000000001-26-000001"  # a 10-Q for the quarter ended 2025-12-31, filed 2026-01-30
    dims = {"0xa": "Individual=Ann;", "0xb": "Individual=Bob;", "0xc": "Individual=Cy;",
            "0xd": "Individual=Di;", "0xe": "Individual=Ed;"}  # fmt: skip
    txts = [
        # Ann adopts in the quarter; shares tagged negative (a sale shown in parentheses)
        _t(q, "TrdArrIndName", "Ann Able", "0xa"), _t(q, "Rule10b51ArrAdoptedFlag", "true", "0xa"),
        _t(q, "TrdArrAdoptionDate", "November 21, 2025", "0xa"),
        _t(q, "TrdArrDuration", "P406D", "0xa"),
        # Bob terminates a plan adopted in an earlier quarter (both dates tagged)
        _t(q, "TrdArrIndName", "Bob Baker", "0xb"), _t(q, "Rule10b51ArrTrmntdFlag", "true", "0xb"),
        _t(q, "TrdArrAdoptionDate", "June 9, 2025", "0xb"),
        _t(q, "TrdArrTerminationDate", "December 1, 2025", "0xb"),
        # Cy: the plan's scheduled end tagged as its termination date (after the filing)
        _t(q, "TrdArrIndName", "Cy Clark", "0xc"),
        _t(q, "TrdArrAdoptionDate", "Nov 1, 2025", "0xc"),
        _t(q, "TrdArrTerminationDate", "September 3, 2026", "0xc"),
        # Di: "as previously disclosed" adoption long before the quarter, flagged again
        _t(q, "TrdArrIndName", "Di Dunn", "0xd"), _t(q, "Rule10b51ArrAdoptedFlag", "true", "0xd"),
        _t(q, "TrdArrAdoptionDate", "June 2, 2025", "0xd"),
        # Ed: a non-Rule 10b5-1 arrangement
        _t(q, "TrdArrIndName", "Ed Eng", "0xe"), _t(q, "NonRule10b51ArrAdoptedFlag", "true", "0xe"),
        _t(q, "TrdArrAdoptionDate", "2025-12-15", "0xe"),
    ]  # fmt: skip
    nums = [dict(_t(q, "TrdArrSecuritiesAggAvailAmt", "-4000", "0xa"), uom="shares")]
    subs = [{"adsh": q, "cik": "320193", "name": "X", "form": "10-Q", "period": "20251231",
             "filed": "20260130"}]  # fmt: skip
    _, plans, _ = ecd.parse_notes_zip(_zip(tmp_path, subs, nums, txts, dims))
    got = {(r["person_name"], r["action"]): r for r in plans}
    assert set(got) == {("Ann Able", "adopted"), ("Bob Baker", "terminated"),
                        ("Cy Clark", "adopted"), ("Ed Eng", "adopted")}  # fmt: skip
    ann = got["Ann Able", "adopted"]
    assert (ann["plan_date"], ann["shares"], ann["duration_days"], ann["plan_type"]) == (
        date(2025, 11, 21),
        4000.0,
        406,
        "rule_10b5_1",
    )
    bob = got["Bob Baker", "terminated"]
    assert bob["plan_date"] == date(2025, 12, 1)
    assert bob["original_adoption_date"] == date(2025, 6, 9)
    assert got["Cy Clark", "adopted"]["expiration_date"] == date(2026, 9, 3)
    assert got["Ed Eng", "adopted"]["plan_type"] == "non_rule_10b5_1"


def test_pay_table_assembles_peo_and_neo_average(tmp_path, db, client, auth, ingested_aapl):
    a = "0001308179-26-000008"
    dims = {"0xp": "ExecutiveCategory=Peo;Individual=Cook;",
            "0xn1": "ExecutiveCategory=NonPeoNeo;Individual=Kate;",
            "0xm1": "Measure=1;", "0xm2": "Measure=2;"}  # fmt: skip
    nums, txts = [], []
    for fy, peo, cap, tsr in (("20250930", 74294811, 108421987, 220.75),
                              ("20240930", 74609802, 168980568, 208.42)):  # fmt: skip
        for tag, v in (("PeoTotalCompAmt", peo), ("PeoActuallyPaidCompAmt", cap),
                       ("NonPeoNeoAvgTotalCompAmt", 27000000),
                       ("NonPeoNeoAvgCompActuallyPaidAmt", 30000000),
                       ("TotalShareholderRtnAmt", tsr), ("PeerGroupTotalShareholderRtnAmt", 190.1),
                       ("CoSelectedMeasureAmt", 416161000000)):  # fmt: skip
            nums.append(dict(_t(a, tag, v, ddate=fy), qtrs="4", uom="USD"))
        nums.append(dict(_t(a, "NetIncomeLoss", 112010000000, ddate=fy, version="us-gaap/2024"),
                         qtrs="4", uom="USD"))  # fmt: skip
        txts += [
            dict(_t(a, "PeoName", "Mr. Cook", "0xp", ddate=fy), qtrs="4"),
            dict(_t(a, "PeoName", "Kate Adams", "0xn1", ddate=fy), qtrs="4"),
        ]
    txts += [
        dict(_t(a, "MeasureName", "Operating Income", "0xm2", ddate="20250930"), qtrs="4"),
        dict(_t(a, "MeasureName", "Net Sales", "0xm1", ddate="20250930"), qtrs="4"),
        dict(_t(a, "CoSelectedMeasureName", "Net Sales", ddate="20250930"), qtrs="4"),
    ]
    subs = [{"adsh": a, "cik": "320193", "name": "APPLE", "form": "DEF 14A", "period": "20260228",
             "filed": "20260108"}]  # fmt: skip
    ecd.load(db, _zip(tmp_path, subs, nums, txts, dims))
    body = client.get(f"/v1/companies/{CIK}/executive-pay", headers=auth).json()
    assert body["labels"]["disclaimer"] == "Information, not signals. Not investment advice."
    assert body["labels"]["basis"].startswith("As disclosed in the proxy")
    assert body["currency"] == "USD" and body["proxy"]["accession_number"] == a
    assert body["proxy"]["source_url"].startswith("https://www.sec.gov/Archives/")
    y = body["years"][0]
    # D-10b: the data sets round year ends to the month end; the 10-K's period of report gives
    # the exact one (the fixture has the FY2024 10-K, period 2024-09-28, and no FY2025 10-K)
    assert y["fiscal_year_end"] == "2025-09-30" and y["fiscal_year_end_rounded"] is True
    fy24_row = body["years"][1]
    assert fy24_row["fiscal_year_end"] == "2024-09-28"
    assert fy24_row["fiscal_year_end_rounded"] is False
    assert executive_pay.month_end(date(2024, 9, 28)) == date(2024, 9, 30)
    assert executive_pay.month_end(date(2025, 1, 3)) == date(2024, 12, 31)
    assert executive_pay.month_end(date(2025, 2, 1)) == date(2025, 1, 31)
    assert y["peo"] == [{"name": "Mr. Cook", "total_comp": 74294811,
                         "comp_actually_paid": 108421987}]  # fmt: skip
    assert y["neo_average"] == {"total_comp": 27000000, "comp_actually_paid": 30000000,
                                "names": ["Kate Adams"]}  # fmt: skip
    assert (y["tsr"], y["peer_tsr"], y["net_income"]) == (220.75, 190.1, 112010000000)
    assert y["company_selected_measure"] == {"name": "Net Sales", "value": 416161000000}
    assert body["measures"] == ["Net Sales", "Operating Income"]
    assert len(body["years"]) == 2
    # as_of before the proxy: nothing known yet
    early = client.get(f"/v1/companies/{CIK}/executive-pay?as_of=2026-01-01", headers=auth).json()
    assert early["years"] == [] and early["proxy"] is None
    assert db.query(ProxyPayFact).count() > 0

    # 2026-11-24 (provenance-ui): chat answers the fiscal year asked about, or says it is not in
    # the table; never another year in its place
    def ask(q):
        r = client.post("/v1/chat", json={"message": q, "cik": "320193"}, headers=auth).json()
        assert r["intent"] == "pay", r
        return r["answer"]

    fy24 = ask("How did Apple Inc's CEO pay compare with total shareholder return in fiscal "
               f"2024? (proxy {a})")  # fmt: skip
    assert fy24.startswith("For the fiscal year ended 2024-09-28,") and "$169.0 million" in fy24
    assert "2025-09-30" not in fy24
    latest = ask("What was Apple's CEO pay versus TSR? Proxy filed 2026-01-08.")
    assert latest.startswith("For the fiscal year ended 2025-09-30 (month end; the exact date "
                             "is not in the annual reports loaded here),")  # fmt: skip
    missing = ask("What was Apple's CEO pay versus TSR in FY2021?")
    assert missing.startswith("Fiscal 2021 is not in the pay-versus-performance tables")
    assert "$" not in missing  # no other year's figures in its place


NOTICE = """<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/ownership"
 xmlns:com="http://www.sec.gov/edgar/common"><headerData><submissionType>144</submissionType>
 <filerInfo><filer><filerCredentials><cik>0001590947</cik></filerCredentials></filer>
 </filerInfo></headerData><formData><issuerInfo><issuerCik>0000320193</issuerCik>
 <issuerName>Apple Inc.</issuerName>
 <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>WERNER ROBERT F.
 </nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
 <relationshipsToIssuer><relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer>
 </issuerInfo><securitiesInformation><securitiesClassTitle>Common</securitiesClassTitle>
 <brokerOrMarketmakerDetails><name>Fidelity Brokerage Services LLC</name>
 </brokerOrMarketmakerDetails>
 <noOfUnitsSold>8275</noOfUnitsSold><aggregateMarketValue>860856.53</aggregateMarketValue>
 <noOfUnitsOutstanding>68178692</noOfUnitsOutstanding><approxSaleDate>11/20/2026</approxSaleDate>
 <securitiesExchangeName>NASDAQ</securitiesExchangeName></securitiesInformation>
 <securitiesToBeSold><securitiesClassTitle>Common</securitiesClassTitle>
 <acquiredDate>02/20/2026</acquiredDate>
 <natureOfAcquisitionTransaction>Restricted Stock Vesting</natureOfAcquisitionTransaction>
 <amountOfSecuritiesAcquired>496</amountOfSecuritiesAcquired></securitiesToBeSold>
 <noticeSignature><noticeDate>11/20/2026</noticeDate><planAdoptionDates>
 <planAdoptionDate>05/18/2026</planAdoptionDate></planAdoptionDates></noticeSignature>
 </formData></edgarSubmission>"""


def test_form144_parse():
    n = form144.parse(NOTICE)
    assert n["person_name"] == "WERNER ROBERT F." and n["person_cik"] == "0001590947"
    assert n["shares"] == 8275 and n["aggregate_market_value"] == 860856.53
    assert n["approx_sale_date"] == date(2026, 11, 20) and n["notice_date"] == date(2026, 11, 20)
    assert n["plan_adoption_date"] == date(2026, 5, 18) and n["acquired_count"] == 1
    assert json.loads(n["relationships"]) == ["Officer"]
    assert form144.parse("<html>not a notice</html>") is None


def _form4(db, acc, owner_cik, owner_name, trans_date, shares, code="S"):
    db.add(InsiderFiling(accession_number=acc, issuer_cik=CIK, owner_cik=owner_cik,
                         owner_name=owner_name, form_type="4", filing_date=trans_date,
                         source="test"))  # fmt: skip
    db.add(
        InsiderTransaction(
            accession_number=acc,
            issuer_cik=CIK,
            row_kind="transaction",
            is_derivative=False,
            row_key=f"{acc}-1",
            trans_date=trans_date,
            trans_code=code,
            shares=Decimal(shares),
            price=Decimal("104"),
        )
    )


def _notice(db, acc, person, person_cik, notice_day):
    row = form144.parse(NOTICE)
    row.update(
        accession_number=acc,
        form_type="144",
        filing_date=notice_day,
        notice_date=notice_day,
        person_name=person,
        person_cik=person_cik,
        source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc.replace('-', '')}/",
    )
    db.add(Form144Notice(**row))


def test_insider_plans_endpoint_joins_the_form4(db, client, auth, ingested_aapl):
    d = date(2026, 11, 20)
    _notice(db, "0001959173-26-000001", "WERNER ROBERT F.", "0001590947", d)
    _notice(db, "0001959173-26-000002", "Jane Q. Smith", "0009999999", d)
    _notice(db, "0001959173-26-000003", "Nobody Sells", "0008888888", d)
    _form4(db, "0001415889-26-000001", "0001590947", "Werner Robert F", date(2026, 11, 21), 8275)
    _form4(db, "0001415889-26-000002", "0007777777", "SMITH JANE Q", date(2026, 11, 25), 100)
    _form4(db, "0001415889-26-000003", "0008888888", "SELLS NOBODY", date(2027, 3, 1), 5)  # late
    # an earlier sale, reported before the notice was filed: never the notice's follow-up
    _form4(db, "0001415889-26-000004", "0001590947", "Werner Robert F", date(2026, 11, 17), 999)
    db.add(TradingPlan(cik=CIK, accession_number="0000320193-26-000006", form_type="10-Q",
                       filing_date=date(2026, 1, 30), period=date(2025, 12, 27),
                       member="Individual=KevanParekh", person_name="Kevan Parekh",
                       title="CFO", action="adopted", plan_type="rule_10b5_1",
                       plan_date=date(2025, 11, 21), duration_days=406,
                       expiration_date=date(2026, 12, 31), source="test"))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/insider-plans?since=2025-01-01",
                      headers=auth).json()  # fmt: skip
    assert body["labels"]["disclaimer"] == "Information, not signals. Not investment advice."
    assert body["plans"][0]["person_name"] == "Kevan Parekh"
    assert body["plans"][0]["filing"]["source_url"].startswith("https://www.sec.gov/Archives/")
    sales = {s["person_name"]: s for s in body["proposed_sales"]}
    assert sales["WERNER ROBERT F."]["followed_by"]["match"] == {
        "rule": "same_person_cik",
        "days_after_notice": 1,
    }
    assert sales["WERNER ROBERT F."]["followed_by"]["shares"] == 8275
    assert sales["Jane Q. Smith"]["followed_by"]["match"]["rule"] == "same_person_name"
    assert sales["Nobody Sells"]["followed_by"] is None  # 101 days later: outside the window
    assert sales["Nobody Sells"]["followed_by_status"] == "pending"  # no data set covers it yet
    assert sales["WERNER ROBERT F."]["followed_by_status"] == "matched"
    assert "first sale (code S)" in " ".join(body["notes"])
    events = insider_plans.emit_plan_events(db) + form144.emit_events(db)
    assert {e.event_type for e in events} == {"sec.trading_plan_adopted", "sec.proposed_sale"}
    db.commit()
    tl_url = f"/v1/companies/{CIK}/timeline?types=trading_plan,proposed_sale&from=2025-01-01"
    tl = client.get(tl_url, headers=auth).json()
    kinds = {i["type"] for i in tl["data"]}
    assert kinds == {"trading_plan", "proposed_sale"}
    assert any(i["title"] == "Kevan Parekh adopted a trading plan" for i in tl["data"])


def test_first_form144_load_is_backfill_and_never_alerts(db, ingested_aapl):
    from datetime import timedelta

    today = date(2026, 11, 24)
    _notice(db, "0001959173-26-000101", "WERNER ROBERT F.", "0001590947", today)
    db.commit()
    first = form144.emit_events(db, today=today)
    assert [e.stream_status for e in first] == ["skipped"]  # filed today, but backfill
    db.commit()
    _notice(db, "0001959173-26-000102", "Jane Q. Smith", "0009999999", today + timedelta(days=1))
    db.commit()
    later = form144.emit_events(db, today=today + timedelta(days=1))
    assert [e.stream_status for e in later] == ["pending"]  # new since the last run


def test_form144_load_skips_a_failed_fetch_and_goes_on(db, ingested_aapl):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.db.models import Filing
    from app.services.sec_client import SecUnavailable

    for acc in ("0001959173-26-000201", "0001959173-26-000202"):
        db.add(Filing(cik=CIK, accession_number=acc, form_type="144",
                      filing_date=date(2026, 11, 20), primary_document="xsl144X01/primary_doc.xml",
                      source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc}-index.html",
                      first_detected_at=datetime.now(UTC), quality_status="ok"))  # fmt: skip
    db.commit()

    class Client:
        def get_text(self, url):
            if "000201" in url:
                raise SecUnavailable("SEC endpoint returned 504 after retries", 504, url)
            return SimpleNamespace(data=NOTICE)

    stats = form144.load(db, Client(), date(2026, 11, 1))
    assert (stats["stored"], stats["failed"]) == (1, 1)  # the next run picks up the failed one
