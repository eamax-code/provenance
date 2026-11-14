"""The outreach example: a screen as of a date against today's (examples/point_in_time.py)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "clients" / "python" / "src"))


def _load():
    spec = importlib.util.spec_from_file_location("pit", ROOT / "examples" / "point_in_time.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    def screen(self, metric, year, as_of=None):
        today = [{"cik": "1", "value": 100}, {"cik": "2", "value": 90}, {"cik": "3", "value": 50}]
        then = [{"cik": "1", "value": 95}, {"cik": "3", "value": 50}]
        return then if as_of else today


def test_compare_finds_look_ahead_and_restatements():
    r = _load().compare(FakeClient(), "revenue", 2023, "2024-03-31", top=2)
    assert [x["cik"] for x in r["unknown"]] == ["2"]  # filed after the date
    assert [(a["value"], b["value"]) for a, b in r["restated"]] == [(95, 100)]
    assert [x["cik"] for x in r["top"]] == ["1", "2"]
