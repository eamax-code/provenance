"""Q-07: activist stakes (docs/contracts/activists.md): chains, the group's figure, the change at
each amendment, exits, 13G-to-13D switches and Item 4 quoted as filed with its filing cited."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.db.models import BeneficialOwner, Company, Schedule13DPurpose

CO, OTHER = "0000000951", "0000000952"
FUND, FUND2, PERSON = "0001517137", "0001517138", "0001900001"
LONG = ("The Reporting Persons acquired the Shares because they believe the Issuer is "
        "undervalued. ") * 12  # fmt: skip


def _filing(db, subject, acc, form, filed, persons, filer=FUND, purpose=None, cls=None, amend=None,
            event=None):  # fmt: skip
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(subject)}/{acc.replace('-', '')}"
    url = f"{folder}/{acc}-index.html"
    for i, (name, cik, typ, shares, pct) in enumerate(persons):
        db.add(BeneficialOwner(subject_cik=subject, accession_number=acc, form_type=form,
                               filing_date=filed, event_date=event, filer_cik=filer, position=i,
                               holder_name=name, holder_cik=cik, holder_type=typ, shares=shares,
                               percent=pct, source_url=url))  # fmt: skip
    if "13D" in form:
        db.add(Schedule13DPurpose(accession_number=acc, subject_cik=subject, purpose=purpose,
                                  source_url=url.replace("-index.html", ".xml"),
                                  class_title=cls, amendment_number=amend))  # fmt: skip


@pytest.fixture
def seeded(db):
    now = datetime.now(UTC)
    for cik, name in ((CO, "TARGETCO INC"), (OTHER, "OTHERCO INC")):
        db.add(Company(cik=cik, legal_name=name, ticker=name[:4],
                       source_url="https://www.sec.gov/", first_detected_at=now,
                       last_processed_at=now, quality_status="ok"))  # fmt: skip
    fund = ("Starboard Value LP", FUND, "PN", 3_700_000, 6.2)
    smith = ("Jeffrey C. Smith", None, "IN", 3_700_000, 6.2)
    # a 13G first (passive), then the 13D chain of three with a group of two reporting persons
    _filing(
        db,
        CO,
        "0001517137-25-000001",
        "SCHEDULE 13G",
        date(2025, 3, 1),
        [("Starboard Value LP", FUND, "PN", 2_800_000, 5.4)],
    )
    _filing(db, CO, "0001517137-26-000001", "SCHEDULE 13D", date(2026, 3, 4), [fund, smith],
            purpose=LONG, cls="Class A Common Stock, par value $0.01 per share",
            event=date(2026, 3, 2))  # fmt: skip
    _filing(db, CO, "0001517137-26-000002", "SCHEDULE 13D/A", date(2026, 6, 2),
            [("Starboard Value LP", FUND, "PN", 5_400_000, 9.1),
             ("Jeffrey C. Smith", None, "IN", 5_400_000, 9.1)],
            purpose="Item 4 is amended to add: the Reporting Persons nominated two directors.",
            cls="Class A Common Stock", amend=1)  # fmt: skip
    # Amendment No. 2 by another member of the group: Item 4 only says it is unchanged
    _filing(db, CO, "0001517138-26-000003", "SCHEDULE 13D/A", date(2026, 10, 2),
            [("Starboard Value Fund", FUND2, "PN", 5_450_000, 9.15),
             ("Starboard Value LP", FUND, "PN", 5_450_000, 9.15)], filer=FUND2,
            purpose="Item 4 remains unchanged.", cls="Class A Common Stock", amend=2)  # fmt: skip
    # an individual's chain that exits, then comes back with a new original 13D
    _filing(
        db,
        CO,
        "0001900001-26-000001",
        "SCHEDULE 13D",
        date(2026, 1, 5),
        [("Pat Doe", PERSON, "IN", 900_000, 7.0)],
        filer=PERSON,
        purpose="Investment.",
    )
    _filing(
        db,
        CO,
        "0001900001-26-000002",
        "SCHEDULE 13D/A",
        date(2026, 9, 3),
        [("Pat Doe", PERSON, "IN", 500_000, 4.1)],
        filer=PERSON,
        amend=1,
    )
    _filing(
        db,
        CO,
        "0001900001-26-000009",
        "SCHEDULE 13D",
        date(2026, 11, 10),
        [("Pat Doe", PERSON, "IN", 800_000, 6.0)],
        filer=PERSON,
        purpose="Back again.",
    )
    _filing(
        db,
        OTHER,
        "0001900001-26-000004",
        "SCHEDULE 13D",
        date(2026, 11, 12),
        [("Pat Doe", PERSON, "IN", 1_000_000, 5.5)],
        filer=PERSON,
        purpose="Engagement.",
    )
    # a group whose members each report only their own shares: under 5% throughout (FONAR)
    g1 = ("Owner One", "0001900011", "IN", 100, 1.9)
    g2 = ("Owner Two", "0001900012", "IN", 90, 1.7)
    _filing(db, OTHER, "0001900011-26-000001", "SCHEDULE 13D", date(2026, 2, 1), [g1, g2],
            filer="0001900011", purpose="Going private.")  # fmt: skip
    _filing(db, OTHER, "0001900011-26-000002", "SCHEDULE 13D/A", date(2026, 5, 1),
            [("Owner One", "0001900011", "IN", 105, 1.95), g2], filer="0001900011",
            amend=1)  # fmt: skip
    # 18.1 to 18.2 is an increase of 0.1 points (Bitdeer)
    _filing(
        db,
        OTHER,
        "0001900021-26-000001",
        "SCHEDULE 13D",
        date(2026, 3, 1),
        [("Tether", "0001900021", "CO", 100, 18.1)],
        filer="0001900021",
        purpose="Hold.",
    )
    _filing(
        db,
        OTHER,
        "0001900021-26-000002",
        "SCHEDULE 13D/A",
        date(2026, 4, 1),
        [("Tether", "0001900021", "CO", 101, 18.2)],
        filer="0001900021",
        amend=1,
    )
    db.commit()


def test_a_chain_its_group_figure_changes_and_carried_purpose(client, auth, seeded):
    body = client.get(f"/v1/companies/{CO}/activists", headers=auth).json()
    assert [d["filer"]["name"] for d in body["data"]] == ["Starboard Value LP", "Pat Doe"]
    sb = body["data"][0]
    assert [c["percent"] for c in sb["chain"]] == [6.2, 9.1, 9.15]  # the group's, never a sum
    assert [c["change_pct_points"] for c in sb["chain"]] == [None, 2.9, 0.05]
    assert [c["amendment_number"] for c in sb["chain"]] == [None, 1, 2]
    assert sb["current"]["class_label"] == "Class A common stock"
    assert sb["current"]["shares"] == 5_450_000 and sb["status"] == "current"
    assert {g["type_label"] for g in sb["group"]} == {"partnership"}  # the latest filing's group
    # Amendment No. 2 says Item 4 is unchanged: No. 1's statement, citing No. 1
    p = sb["purpose"]
    assert p["accession_number"] == "0001517137-26-000002" and p["carried_forward"] is True
    assert p["excerpt"].startswith("Item 4 is amended to add") and p["truncated"] is False
    assert sb["switched_from_13g"]["form"] == "SCHEDULE 13G"
    assert sb["first_filed"]["percent"] == 6.2
    assert body["labels"]["disclaimer"].startswith("Information, not signals")
    assert "api" not in str(body).lower().replace("api_", "")  # no API URLs


def test_exit_then_a_new_original_starts_a_new_chain(client, auth, seeded):
    body = client.get(f"/v1/companies/{CO}/activists?status=all", headers=auth).json()
    doe = [d for d in body["data"] if d["filer"]["name"] == "Pat Doe"]
    assert [d["status"] for d in doe] == ["current", "exited"]
    assert doe[1]["current"]["percent"] == 4.1  # the exit filing is `current`
    assert body["data"][-1]["status"] == "exited"  # current chains first, then exited
    early = client.get(f"/v1/companies/{CO}/activists?as_of=2026-04-01", headers=auth).json()
    assert {d["filer"]["name"] for d in early["data"]} == {"Starboard Value LP", "Pat Doe"}
    assert early["data"][0]["current"]["percent"] == 7.0  # Doe's 7.0 before Starboard's 6.2


def test_a_long_purpose_is_cut_at_a_sentence(client, auth, seeded):
    body = client.get(f"/v1/companies/{CO}/activists?as_of=2026-03-31", headers=auth).json()
    p = next(d for d in body["data"] if d["filer"]["name"] == "Starboard Value LP")["purpose"]
    assert p["truncated"] is True and len(p["excerpt"]) <= 600 and p["excerpt"].endswith(".")
    assert "\n" not in p["excerpt"] and "<" not in p["excerpt"]


def test_across_companies_kinds_and_filters(client, auth, seeded):
    q = "since=2026-01-01&until=2026-11-25"
    rows = client.get(f"/v1/activists?{q}&kind=all", headers=auth).json()["data"]
    kinds = {r["accession_number"]: r["kind"] for r in rows}
    assert kinds == {"0001517137-26-000001": "switched", "0001517137-26-000002": "increased",
                     "0001517138-26-000003": "amended", "0001900001-26-000001": "new",
                     "0001900001-26-000002": "exited", "0001900001-26-000009": "new",
                     "0001900001-26-000004": "new",
                     "0001900011-26-000001": "new", "0001900011-26-000002": "amended",
                     "0001900021-26-000001": "new",
                     "0001900021-26-000002": "increased"}  # fmt: skip
    new = client.get(f"/v1/activists?{q}", headers=auth).json()["data"]
    assert len(new) == 6 and new[0]["filed_date"] == "2026-11-12"  # newest first
    sw = client.get(f"/v1/activists?{q}&kind=switched", headers=auth).json()["data"]
    assert sw[0]["switched_from_13g"]["percent"] == 5.4 and sw[0]["group_size"] == 2
    assert sw[0]["event_date"] == "2026-03-02"
    big = client.get(f"/v1/activists?{q}&kind=all&min_percent=9", headers=auth).json()["data"]
    assert {r["percent"] for r in big} == {9.1, 9.15, 18.1, 18.2}
    wide = client.get("/v1/activists?since=2025-01-01&until=2026-11-25", headers=auth)
    assert wide.status_code == 422 and wide.json()["error"]["code"] == "invalid_parameter"


def test_a_chain_never_at_5_percent_is_not_exited(client, auth, seeded):
    body = client.get(f"/v1/companies/{OTHER}/activists?status=all", headers=auth).json()
    group = next(d for d in body["data"] if d["filer"]["cik"] == "0001900011")
    assert group["status"] == "current" and group["current"]["percent"] == 1.95


def test_errors_and_the_demo_key(client, auth, seeded, settings, monkeypatch):
    assert client.get("/v1/companies/0000000999/activists", headers=auth).status_code == 404
    monkeypatch.setattr(settings, "public_showcase_ciks", OTHER)
    demo = {"X-API-Key": "demo"}
    rows = client.get("/v1/activists?since=2026-01-01&until=2026-11-25&kind=all",
                      headers=demo).json()["data"]  # fmt: skip
    assert {r["company"]["cik"] for r in rows} == {OTHER}  # showcase companies only
    assert client.get(f"/v1/companies/{CO}/activists", headers=demo).status_code == 403


def test_the_list_is_rebuilt_when_a_13d_is_added(client, auth, db, seeded):
    q = "/v1/activists?since=2026-11-01&until=2026-11-25"
    before = client.get(q, headers=auth).json()["data"]
    _filing(
        db,
        OTHER,
        "0001900031-26-000001",
        "SCHEDULE 13D",
        date(2026, 11, 20),
        [("New Fund", "0001900031", "PN", 100, 6.0)],
        filer="0001900031",
        purpose="Value.",
    )
    db.commit()
    after = client.get(q, headers=auth).json()["data"]
    assert len(after) == len(before) + 1 and after[0]["filer"]["name"] == "New Fund"


def _walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from _walk(v)


def _clean(body):
    import json

    raw = json.dumps(body).lower()
    for banned in ("first_detected_at", "source_updated_at", "cusip", "data.sec.gov"):
        assert banned not in raw, banned
    urls = [v for k, v in _walk(body) if k.endswith("url") and v]
    assert urls and all(u.startswith("https://www.sec.gov/Archives/") for u in urls), urls


def test_api_and_mcp_carry_no_internal_field_or_api_url(client, auth, seeded):
    import json

    _clean(client.get(f"/v1/companies/{CO}/activists?status=all", headers=auth).json())
    _clean(client.get("/v1/activists?since=2026-01-01&until=2026-11-25&kind=all",
                      headers=auth).json())  # fmt: skip
    for name, args in (("company_activists", {"cik": CO, "status": "all"}),
                       ("activist_stakes", {"since": "2026-01-01", "until": "2026-11-25",
                                            "kind": "all"})):  # fmt: skip
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": args}}  # fmt: skip
        res = client.post("/mcp", json=rpc, headers=auth).json()["result"]
        assert res["isError"] is False, res
        body = json.loads(res["content"][0]["text"])
        assert body["data"]
        _clean(body)


def test_chat_answers_both_questions_quoting_item_4_as_filed(client, auth, seeded):
    from app.services.chat_intents import detect
    from app.services.conversation import activist_request

    assert detect("Who are the activists at Tesla?") == "activists"
    assert detect("Who files a 13D on Tesla?") == "five_percent"  # unchanged
    assert activist_request("new activist stakes this month")["kind"] == "new"
    one = client.post("/v1/chat", json={"message": "Who are the activists?", "cik": CO},
                      headers=auth).json()  # fmt: skip
    assert one["intent"] == "activists" and one["answered_by"] == "data", one
    assert "Starboard Value LP" in one["answer"] and "9.15%" in one["answer"]
    assert (
        "Item 4 is amended to add: the Reporting Persons nominated two directors." in one["answer"]
    )  # quoted as filed, from the filing that states it
    assert "Not investment advice" in one["answer"] and "December 2024" in one["answer"]
    (table,) = [b for b in one["blocks"] if b.get("type") == "table"]
    assert table["columns"][0] == "Filer" and len(table["rows"]) == 2
    many = client.post("/v1/chat", json={"message": "new activist stakes in the last 2 years"},
                       headers=auth).json()  # fmt: skip
    assert many["intent"] == "activists" and "Not investment advice" in many["answer"], many
    (t2,) = [b for b in many["blocks"] if b.get("type") == "table"]
    assert {r[0]["text"] for r in t2["rows"]} == {"TARGETCO INC", "OTHERCO INC"}
