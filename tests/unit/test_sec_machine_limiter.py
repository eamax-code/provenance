"""One SEC request budget per machine, shared across processes, with a shared back-off."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import sec_client
from app.services.sec_client import MachineLimiter, _immutable


class FakeClock:
    """Time that moves only when the code sleeps: the tests assert the spacing the limiter asks
    for, not wall time, so a loaded machine cannot fail them."""

    def __init__(self) -> None:
        self.now, self.slept = 1_000.0, []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(sec_client, "time", SimpleNamespace(time=c.time, sleep=c.sleep))
    return c


def test_interval_is_shared_through_the_file(tmp_path, clock):
    path = tmp_path / "rate"
    a, b = MachineLimiter(path, 20), MachineLimiter(path, 20)  # two processes, one file
    for limiter in (a, b, a, b, a):
        limiter.wait()
    # the first request goes at once; each later one, from either process, waits 1/20 s
    assert clock.slept == pytest.approx([0.05] * 4)


def test_pause_holds_every_user_of_the_file(tmp_path, clock):
    path = tmp_path / "rate"
    MachineLimiter(path, 100).pause(0.2)
    MachineLimiter(path, 100).wait()  # another process sharing the file
    assert clock.slept == pytest.approx([0.2])


def test_only_filed_documents_are_served_from_cache_without_asking():
    assert _immutable("https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/a.htm")
    assert _immutable(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/"
        "0000320193-24-000123-index.html"
    )
    assert not _immutable("https://data.sec.gov/submissions/CIK0000320193.json")
    assert not _immutable("https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/")
