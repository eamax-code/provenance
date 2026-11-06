"""The base-rate arithmetic of scripts/backtest_officer_changes.py (ticket 20)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import backtest_officer_changes as bt  # noqa: E402


def test_company_years_count_changes_inside_each_fiscal_year():
    years = [
        ("A", 2020, date(2020, 12, 31), 100, 10, "73"),
        ("A", 2021, date(2021, 12, 31), 110, 11, "73"),
        ("A", 2022, date(2022, 12, 31), 121, 20, "73"),
    ]
    changes = [("A", date(2021, 3, 1)), ("A", date(2021, 9, 1)), ("A", date(2022, 2, 1))]
    rows = bt.company_years(years, changes)
    assert len(rows) == 1  # only 2021 has a year before and after
    r = rows[0]
    assert r["fy"] == 2021 and r["changes"] == 2 and round(r["growth"], 3) == 0.1
    assert round(r["dmargin"], 4) == round(20 / 121 - 11 / 110, 4)


def test_peers_and_summary():
    rows = [
        {"cik": str(i), "fy": 2021, "sic2": "73", "changes": i % 2, "growth": g, "dmargin": 0.0}
        for i, g in enumerate([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    ]
    out = bt.with_peers(rows)
    assert len(out) == 6 and round(sum(r["excess_growth"] for r in out), 6) == 0.0
    s = bt.summarise([r for r in out if r["changes"] == 1], "odd")
    assert s["company_years"] == 3 and s["beat_peer_growth_pct"] == 66.7
    assert bt.summarise([], "none") == {"group": "none", "company_years": 0}
    small = [dict(r, sic2="99") for r in rows[:4]]
    assert bt.with_peers(small) == []  # fewer than five peers


def test_wilson_interval():
    lo, hi = bt.wilson(50, 100)
    assert lo < 50 < hi and round(hi - lo, 0) == 19
    assert bt.wilson(0, 0) == (0.0, 0.0)
