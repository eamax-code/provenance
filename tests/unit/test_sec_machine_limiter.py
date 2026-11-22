"""One SEC request budget per machine, shared across processes, with a shared back-off."""

from __future__ import annotations

import time

from app.services.sec_client import MachineLimiter, _immutable


def test_interval_is_shared_through_the_file(tmp_path):
    path = tmp_path / "rate"
    a, b = MachineLimiter(path, 20), MachineLimiter(path, 20)  # two processes, one file
    start = time.time()
    for limiter in (a, b, a, b, a):
        limiter.wait()
    assert time.time() - start >= 4 * 0.05 - 0.01


def test_pause_holds_every_user_of_the_file(tmp_path):
    path = tmp_path / "rate"
    MachineLimiter(path, 100).pause(0.2)
    start = time.time()
    MachineLimiter(path, 100).wait()
    assert time.time() - start >= 0.18


def test_only_filed_documents_are_served_from_cache_without_asking():
    assert _immutable("https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/a.htm")
    assert _immutable(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/"
        "0000320193-24-000123-index.html"
    )
    assert not _immutable("https://data.sec.gov/submissions/CIK0000320193.json")
    assert not _immutable("https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/")
