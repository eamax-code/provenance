"""The MCP server over the public API (GH #22)."""

from __future__ import annotations

import json


def rpc(client, method, params=None, rid=1, headers=None):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers or {})


def call(client, name, arguments, headers=None):
    r = rpc(client, "tools/call", {"name": name, "arguments": arguments}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def data(res):
    import json

    return json.loads(res["content"][0]["text"])


def test_initialize_and_list_tools(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "1"}})  # fmt: skip
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-03-26" and res["serverInfo"]["name"] == "provenance"
    assert "tools" in res["capabilities"] and "source_url" in res["instructions"]
    assert (
        rpc(client, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"][
            "protocolVersion"
        ]
        == "2025-11-25"
    )
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202 and note.content == b""
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert set(tools) >= {"search_companies", "company_overview", "get_figures", "list_filings",
                          "recent_events", "listing_events", "rank_companies"}  # fmt: skip
    for t in tools.values():
        assert t["inputSchema"]["type"] == "object" and t["annotations"]["readOnlyHint"] is True
    assert "as_of" in tools["get_figures"]["inputSchema"]["properties"]
    assert rpc(client, "ping").json()["result"] == {}


def test_tools_return_citable_results_with_the_demo_key(client, ingested_aapl, fake_sec):
    import json

    before = len(fake_sec.calls)
    found = json.loads(call(client, "search_companies", {"query": "apple"})["content"][0]["text"])
    assert found["data"][0]["cik"] == "0000320193"
    res = call(client, "get_figures", {"cik": "320193", "metric": "revenue"})
    assert res["isError"] is False
    facts = json.loads(res["content"][0]["text"])["data"]
    assert facts and all(f["source_url"].startswith("https://www.sec.gov/") for f in facts)
    assert all(f["accession_number"] for f in facts)
    args = {"cik": "320193", "metric": "revenue", "as_of": "2024-01-15"}
    past = data(call(client, "get_figures", args))
    assert all(f["filed_date"] <= "2024-01-15" for f in past["data"])
    filings = json.loads(
        call(client, "list_filings", {"cik": "320193", "limit": 3})["content"][0]["text"]
    )
    assert len(filings["data"]) == 3 and filings["data"][0]["source_url"].startswith(
        "https://www.sec.gov/"
    )
    assert len(fake_sec.calls) == before  # the demo key never reaches the SEC


def test_tool_errors_come_back_as_results_not_crashes(client, ingested_aapl):
    res = call(client, "get_figures", {"cik": "320193"})  # metric missing
    assert res["isError"] is True and "metric" in res["content"][0]["text"]
    res = call(client, "company_overview", {"cik": "../etc"})
    assert res["isError"] is True and "digits" in res["content"][0]["text"]
    res = call(client, "get_figures", {"cik": "320193", "metric": "revenue", "drop": 1})
    assert res["isError"] is True and "unknown argument" in res["content"][0]["text"]
    res = call(client, "list_filings", {"cik": "789019"})  # not a showcase company for the demo
    assert res["isError"] is True and res["content"][0]["text"].startswith("demo_scope")
    r = rpc(client, "tools/call", {"name": "drop_tables", "arguments": {}})
    assert r.json()["error"]["code"] == -32602
    assert rpc(client, "resources/list").json()["error"]["code"] == -32601
    bad = client.post("/mcp", content=b"{not json", headers={"Content-Type": "application/json"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    assert client.post("/mcp", json={"id": 1}).json()["error"]["code"] == -32600


def test_the_callers_key_is_used_and_metered(client, auth, ingested_aapl):
    import json

    key = auth["X-API-Key"]
    for headers in ({"X-API-Key": key}, {"Authorization": f"Bearer {key}"}):
        res = call(client, "list_filings", {"cik": "320193", "limit": 20}, headers=headers)
        assert res["isError"] is False and len(json.loads(res["content"][0]["text"])["data"]) == 6
    demo = call(client, "list_filings", {"cik": "320193", "limit": 20})
    assert demo["isError"] is True and "demo_limit" in demo["content"][0]["text"]
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert usage["requests_by_route"].get("/v1/companies/{cik}/filings (mcp)", 0) >= 2
    nope = {"X-API-Key": "pk_live_nope"}
    bad = call(client, "list_filings", {"cik": "320193"}, headers=nope)
    assert bad["isError"] is True and "invalid_api_key" in bad["content"][0]["text"]


def test_batch_and_get(client):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    r = client.post("/mcp", json=[ping, note])
    assert r.status_code == 200 and [a["id"] for a in r.json()] == [1]
    assert client.get("/mcp").status_code == 405


def test_mcp_is_documented(client):
    assert "/mcp" in client.get("/llms.txt").text
    html = client.get("/developers/").text
    assert "claude mcp add --transport http provenance" in html and 'id="mcp"' in html


def test_oversized_requests_are_refused(client):
    big = b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "pad": "' + b"x" * 300_000 + b'"}'
    r = client.post("/mcp", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == -32600


def test_statements_and_timeline_tools(client, ingested_aapl, items_aapl, fake_sec):
    before = len(fake_sec.calls)
    tools = {t["name"]: t for t in rpc(client, "tools/list").json()["result"]["tools"]}
    for name in ("company_statements", "company_timeline"):
        assert "as_of" in tools[name]["inputSchema"]["properties"]
        assert tools[name]["annotations"]["readOnlyHint"] is True
    res = call(client, "company_statements", {"cik": "320193", "statement": "income"})
    assert res["isError"] is False, res
    body = data(res)
    cells = [c for r in body["rows"] if not r["derived"] for c in r["cells"] if c]
    assert cells and all(
        c["source_url"].startswith("https://www.sec.gov/Archives/") and c["accession_number"]
        and c["mapping_version"] and isinstance(c["value"], float) for c in cells
    )  # fmt: skip
    past = data(call(client, "company_statements",
                     {"cik": "320193", "statement": "income", "as_of": "2024-01-15"}))  # fmt: skip
    assert past["as_of"] == "2024-01-15"
    assert all(c["filed_date"] <= "2024-01-15" for r in past["rows"] for c in r["cells"]
               if c and c.get("filed_date"))  # fmt: skip
    bad = call(client, "company_statements", {"cik": "320193", "statement": "../stats"})
    assert bad["isError"] is True
    tl = data(call(client, "company_timeline", {"cik": "320193", "types": "filing", "limit": 5}))
    assert tl["data"] and all(i["type"] == "filing" for i in tl["data"])
    assert all(i["filing_url"].startswith("https://www.sec.gov/Archives/") for i in tl["data"])
    text = json.dumps(tl) + json.dumps(body)
    assert "data.sec.gov" not in text and "first_detected" not in text
    assert len(fake_sec.calls) == before
