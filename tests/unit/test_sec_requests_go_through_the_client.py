"""Every request to sec.gov goes through the SEC client (contact User-Agent, machine-wide rate
limit, shared back-off): no curl, wget, httpx, requests or urllib call to a sec.gov URL anywhere
else in app/ or scripts/. 2026-11-22: a curl loop outside the limiter downloaded data sets while
other jobs used the budget."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {"app/services/sec_client.py", "scripts/sec_fetch.py"}  # the client and its CLI
SEC_URL = re.compile(r"https?://[a-z.]*sec\.gov", re.I)
LIBS = r"\b(httpx|requests|urllib\.request|urllib3)\b\s*\.\s*"
CALLS = r"(get|post|head|request|stream|Client|AsyncClient|urlopen|PoolManager)"
DIRECT = re.compile(r"\b(curl|wget)\b|" + LIBS + CALLS)


def test_no_direct_sec_requests_outside_the_client():
    offenders = []
    for path in [*ROOT.glob("app/**/*.py"), *ROOT.glob("scripts/**/*.py"),
                 *ROOT.glob("scripts/**/*.sh")]:  # fmt: skip
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or "__pycache__" in rel:
            continue
        text = path.read_text(errors="replace")
        if SEC_URL.search(text) and DIRECT.search(text):
            offenders.append(rel)
    assert offenders == [], f"use SecClient or scripts/sec_fetch.py: {offenders}"


def test_the_check_catches_a_curl_and_an_httpx_call():
    assert DIRECT.search("curl -s -o x https://www.sec.gov/files/x.zip")
    assert DIRECT.search('httpx.get("https://data.sec.gov/submissions/CIK1.json")')
    assert not DIRECT.search("SecClient(settings).get_text(url)")
