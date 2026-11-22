"""MCP server over the public API (GH #22).

`POST /mcp` speaks the Model Context Protocol's Streamable HTTP transport with plain JSON
responses: JSON-RPC 2.0 for `initialize`, `ping`, `tools/list` and `tools/call`. Each tool is a
call to the documented REST endpoint, made in process with the caller's own key and address,
so the same authentication, demo limits, quotas and usage metering apply, and every result keeps
the filing URL and accession number an agent needs to cite it.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import DEMO_KEY, client_ip
from app.services.fact_normalizer import SUPPORTED_METRICS
from app.services.ratios import DERIVED_METRICS

router = APIRouter(include_in_schema=False)

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "provenance", "title": "Provenance", "version": "0.1.0"}
INSTRUCTIONS = (
    "Provenance answers questions about US public companies from their SEC filings, and about "
    "new listings in Canada, the UK and the EU. Every figure and filing has a source_url on "
    "sec.gov (or the regulator) and an accession number: cite them whenever you state a value. "
    "Find a company with search_companies first, then use its CIK. Values are as reported; a "
    "missing value means the filings did not contain it, not zero. Not investment advice."
)
MAX_TEXT = 60_000  # characters per tool result, so one call cannot flood the agent's context

_CIK = {"type": "string", "description": "SEC CIK, with or without leading zeros, e.g. 320193"}
_METRIC = {
    "type": "string",
    "enum": list(SUPPORTED_METRICS) + list(DERIVED_METRICS),
    "description": "A reported figure, or a derived one (margins, returns, free cash flow, "
    "ratios) that lists its two inputs",
}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}

TOOLS: dict[str, dict[str, Any]] = {
    "search_companies": {
        "title": "Find a company",
        "description": "Find US public companies by ticker, CIK or name (former names and typos "
        "work). Returns each company's CIK, which the other tools take.",
        "path": "/v1/companies/search",
        "params": {"query": "q", "limit": "limit"},
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ticker, CIK or name"},
                "limit": _LIMIT,
            },  # fmt: skip
            "required": ["query"],
        },
    },
    "company_overview": {
        "title": "Company overview",
        "description": "A cited profile of one company: identity, latest annual figures, revenue "
        "by fiscal year, recent filings and leadership changes, each linked to its filing.",
        "path": "/v1/companies/{cik}/profile",
        "params": {},
        "schema": {"type": "object", "properties": {"cik": _CIK}, "required": ["cik"]},
    },
    "get_figures": {
        "title": "Financial figures",
        "description": "Reported values of one metric for a company, newest first, each with its "
        "filing (source_url, accession_number, form_type, filed_date). Set as_of to see only "
        "what had been filed by that date.",
        "path": "/v1/companies/{cik}/facts",
        "params": {"metric": "metric", "period": "period", "as_of": "as_of", "limit": "limit"},
        "schema": {
            "type": "object",
            "properties": {
                "cik": _CIK,
                "metric": _METRIC,
                "period": {"type": "string", "enum": ["annual", "quarterly"], "default": "annual"},
                "as_of": _DATE,
                "limit": _LIMIT,
            },
            "required": ["cik", "metric"],
        },
    },
    "company_connections": {
        "title": "Insiders, subsidiaries and 5% holders",
        "description": "A company's connections: directors, officers and 10% owners (Forms 3, 4, "
        "5) and the other companies they report on, holders above 5% (Schedules 13D/G) and "
        "subsidiaries (exhibit 21). Each edge carries the filing it comes from; as_of uses only "
        "filings made by that date.",
        "path": "/v1/companies/{cik}/graph",
        "params": {"include": "include", "as_of": "as_of", "former": "former"},
        "schema": {
            "type": "object",
            "properties": {
                "cik": _CIK,
                "include": {
                    "type": "string",
                    "description": "Comma-separated: insiders, interlocks, subsidiaries, holders",
                },
                "as_of": _DATE,
                "former": {
                    "type": "boolean",
                    "description": "Include former insiders and holders now below 5%",
                },
            },
            "required": ["cik"],
        },
    },
    "insider_transactions": {
        "title": "Insider purchases and sales",
        "description": "Transactions reported on Forms 3, 4 and 5, newest first: who, role, "
        "code (P purchase, S sale, A award, M exercise, F tax withholding...), shares, price "
        "and holdings after, each with its filing.",
        "path": "/v1/companies/{cik}/insider-transactions",
        "params": {"code": "code", "since": "since", "as_of": "as_of", "limit": "limit"},
        "schema": {
            "type": "object",
            "properties": {
                "cik": _CIK,
                "code": {"type": "string", "description": "Comma-separated codes, e.g. P,S"},
                "since": _DATE,
                "as_of": _DATE,
                "limit": _LIMIT,
            },
            "required": ["cik"],
        },
    },
    "institutional_ownership": {
        "title": "Institutional holders (13F)",
        "description": "Institutional investment managers holding a company's shares at the "
        "latest complete quarter, from Forms 13F: holder count and change, new/added/reduced/"
        "exited counts, institutional percentage (derived from the cover-page shares "
        "outstanding) and the largest holders by value, each with its 13F filing. as_of uses "
        "only 13Fs filed by that date.",
        "path": "/v1/companies/{cik}/ownership",
        "params": {"as_of": "as_of", "limit": "limit"},
        "schema": {
            "type": "object",
            "properties": {"cik": _CIK, "as_of": _DATE, "limit": _LIMIT},
            "required": ["cik"],
        },
    },
    "company_segments": {
        "title": "Segments",
        "description": "Revenue and segment profit (operating income, or pretax income for "
        "banks) by business segment, geography and product, for up to three fiscal years, from "
        "the latest annual report; each kind says whether the segments add up to the "
        "consolidated figure (status ok or unreconciled) and links its filing.",
        "path": "/v1/companies/{cik}/segments",
        "params": {"as_of": "as_of"},
        "schema": {
            "type": "object",
            "properties": {"cik": _CIK, "as_of": _DATE},
            "required": ["cik"],
        },
    },
    "companies_going_public": {
        "title": "Companies going public",
        "description": "First-time registrants going public, newest activity first, with the "
        "stage reached (confidential DRS, filed S-1/F-1 or Form 10, amended, effective, listing "
        "8-A/CERT, priced 424B4, withdrawn) and the filing behind each milestone. EDGAR is read "
        "every hour.",
        "path": "/v1/ipos",
        "params": {
            "days": "days",
            "since": "since",
            "stage": "stage",
            "kind": "kind",
            "limit": "limit",
        },  # fmt: skip
        "schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Activity in the last N days (90)"},
                "since": _DATE,
                "stage": {
                    "type": "string",
                    "description": "confidential, filed, amended, effective, listing, priced "
                    "or withdrawn",
                },
                "kind": {"type": "string", "description": "ipo or spin_off"},
                "limit": _LIMIT,
            },
        },
    },
    "list_filings": {
        "title": "Recent filings",
        "description": "A company's SEC filings, newest first, with links to each filing.",
        "path": "/v1/companies/{cik}/filings",
        "params": {"form_type": "form_type", "since": "since", "limit": "limit"},
        "schema": {
            "type": "object",
            "properties": {
                "cik": _CIK,
                "form_type": {"type": "string", "description": "e.g. 10-K, 10-Q, 8-K, S-1"},
                "since": _DATE,
                "limit": _LIMIT,
            },
            "required": ["cik"],
        },
    },
    "rank_companies": {
        "title": "Rank companies by a metric",
        "description": "Companies ranked by a metric for one calendar year, optionally as known "
        "on a date. One row per company with its filing.",
        "path": "/v1/facts/screen",
        "params": {
            "metric": "metric",
            "year": "year",
            "as_of": "as_of",
            "order": "order",
            "limit": "limit",
        },  # fmt: skip
        "schema": {
            "type": "object",
            "properties": {
                "metric": _METRIC,
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                "as_of": _DATE,
                "order": {"type": "string", "enum": ["desc", "asc"], "default": "desc"},
                "limit": _LIMIT,
            },
            "required": ["metric", "year"],
        },
    },
    "search_filings": {
        "title": "Search filing text",
        "description": "Passages from filing sections (prospectuses, 8-K officer changes, earnings "
        "releases) matching words, each with its filing link and a snippet.",
        "path": "/v1/search",
        "params": {
            "query": "q",
            "cik": "cik",
            "form": "form",
            "as_of": "as_of",
            "limit": "limit",
        },  # fmt: skip
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "cik": _CIK,
                "form": {"type": "string", "description": "e.g. S-1, 8-K"},
                "as_of": _DATE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "required": ["query"],
        },
    },
    "recent_events": {
        "title": "Event feed",
        "description": "New SEC filings, officer changes from 8-K item 5.02 and listing events, "
        "in order. event_type narrows to what a filing means: sec.ipo_priced (an IPO's final "
        "prospectus), sec.restatement (8-K 4.02), "
        "sec.auditor_change (4.01), sec.bankruptcy (1.03), sec.material_agreement (1.01), "
        "sec.acquisition_completed (2.01), sec.change_in_control (5.01), sec.results (2.02), "
        "sec.shareholder_vote (5.07), sec.late_filing (NT 10-K/Q), sec.deregistration "
        "(Form 15), sec.delisting (Form 25), sec.tender_offer (SC TO-T), sec.merger_proxy "
        "(DEFM14A), sec.officer_change. Pass next_cursor back as after to continue. For webhook "
        "alerts on these types across companies, a Builder key can POST /v1/type-watches.",
        "path": "/v1/events",
        "params": {
            "types": "types",
            "event_type": "event_type",
            "cik": "cik",
            "form_type": "form_type",
            "since": "since",
            "after": "after",
            "limit": "limit",
        },  # fmt: skip
        "schema": {
            "type": "object",
            "properties": {
                "types": {
                    "type": "string",
                    "description": "filing, leadership, listing (comma-separated)",
                },  # fmt: skip
                "event_type": {
                    "type": "string",
                    "description": "Comma-separated, e.g. sec.restatement,sec.bankruptcy",
                },
                "cik": _CIK,
                "form_type": {"type": "string"},
                "since": {
                    "type": "string",
                    "description": "ISO 8601 time, e.g. 2026-11-01T00:00:00Z",
                },
                "after": {"type": "string", "description": "next_cursor from the last call"},
                "limit": _LIMIT,
            },
        },
    },
    "listing_events": {
        "title": "New listings in Canada, the UK and the EU",
        "description": "New listings, delistings and suspensions on covered venues. A "
        "new_listing is an instrument first traded on a venue, not an IPO determination.",
        "path": "/v1/markets/events",
        "params": {
            "types": "types",
            "region": "region",
            "mic": "mic",
            "since": "since",
            "limit": "limit",
        },  # fmt: skip
        "schema": {
            "type": "object",
            "properties": {
                "types": {
                    "type": "string",
                    "description": "One event type per call",
                    "enum": [
                        "new_listing",
                        "delisting",
                        "suspended",
                        "reinstated",
                        "modified",
                        "ipo",
                    ],
                },  # fmt: skip
                "region": {"type": "string", "enum": ["canada", "europe", "uk"]},
                "mic": {"type": "string", "description": "Venue MIC, e.g. XLON"},
                "since": _DATE,
                "limit": _LIMIT,
            },
        },
    },
}


def tool_list() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": t["title"],
            "description": t["description"],
            "inputSchema": t["schema"],
            "annotations": {"readOnlyHint": True, "openWorldHint": False},
        }
        for name, t in TOOLS.items()
    ]


def _rpc_error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _result(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _caller_key(request: Request) -> str:
    """The caller's key from X-API-Key or a bearer token; the public demo key otherwise."""
    key = request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    if not key and auth.lower().startswith("bearer "):
        key = auth[7:].strip()
    return key or DEMO_KEY


def _text(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + '..."[truncated: ask for fewer rows with limit]"'
    return text


async def call_tool(request: Request, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = TOOLS[name]
    schema = tool["schema"]
    missing = [k for k in schema.get("required", []) if args.get(k) in (None, "")]
    if missing:
        raise ValueError(f"missing argument: {', '.join(missing)}")
    unknown = sorted(set(args) - set(schema["properties"]))
    if unknown:
        raise ValueError(f"unknown argument: {', '.join(unknown)}")
    path = tool["path"]
    if "{cik}" in path:
        cik = str(args["cik"]).strip()
        if not cik.isdigit() or len(cik) > 10:
            raise ValueError("cik must be digits, e.g. 320193")
        path = path.replace("{cik}", cik)
    params = {
        api: str(args[arg]).lower() if isinstance(args[arg], bool) else args[arg]
        for arg, api in tool["params"].items()
        if args.get(arg) not in (None, "")
    }
    transport = httpx.ASGITransport(app=request.app, client=(client_ip(request), 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp.internal") as http:
        headers = {"X-API-Key": _caller_key(request), "X-Provenance-Channel": "mcp"}
        r = await http.get(path, params=params, headers=headers)
    try:
        body = r.json()
    except ValueError:
        body = {"error": {"code": "bad_response", "message": "The API returned no JSON."}}
    if r.status_code >= 400 or r.status_code == 202:
        err = body.get("error") or {}
        message = err.get("message") or f"HTTP {r.status_code}"
        if r.status_code == 202:
            message = "The company is being loaded; try again in a minute."
        return {
            "content": [{"type": "text", "text": f"{err.get('code', r.status_code)}: {message}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": _text(body)}], "isError": False}


async def handle(request: Request, msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(
            msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request"
        )
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if rid is None:  # a notification, e.g. notifications/initialized: nothing to answer
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _result(
            rid,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": tool_list()})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return _rpc_error(rid, -32602, f"Unknown tool: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _rpc_error(rid, -32602, "arguments must be an object")
        try:
            return _result(rid, await call_tool(request, name, args))
        except ValueError as exc:
            return _result(rid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return _rpc_error(rid, -32601, f"Method not found: {method}")


MAX_BODY = 256 * 1024  # a JSON-RPC message is small; refuse anything larger before reading it


@router.post("/mcp")
async def mcp(request: Request):
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        return JSONResponse(_rpc_error(None, -32600, "Request too large"), status_code=413)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY:
            return JSONResponse(_rpc_error(None, -32600, "Request too large"), status_code=413)
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)
    if isinstance(payload, list):
        answers = [a for a in [await handle(request, m) for m in payload] if a is not None]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await handle(request, payload)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)


@router.get("/mcp")
def mcp_stream():
    # No server-initiated messages: the transport allows answering GET with 405.
    return Response(status_code=405, headers={"Allow": "POST"})
