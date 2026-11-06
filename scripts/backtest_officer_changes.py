"""Base rates for 8-K item 5.02 (officer and director changes): what followed, against peers.

Ticket 20 asks for measured base rates before any score or weighting. A company-year "has a
change" when the company filed at least one 8-K with item 5.02 during that fiscal year. For every
company-year with revenue in that year and the next (annual-report figures, mart_company_period),
the outcome is the next year's revenue growth and operating-margin change, each compared with the
median of the company's SIC peers (two-digit SIC) for the same fiscal year. The report compares
company-years with and without changes. It describes what happened; it is not a signal.

python scripts/backtest_officer_changes.py \
    --out docs/benchmarks/officer-changes-base-rates-2026-11.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import text

MIN_PEERS = 5
MAX_ABS_GROWTH = 5.0  # drop >500% moves: shells and restarts dominate them


def load(db):
    years = db.execute(
        text(
            """SELECT p.cik, p.fiscal_year, p.period_end, p.revenue, p.operating_income,
                      left(c.sic_code, 2) AS sic2
               FROM mart_company_period p JOIN companies c ON c.cik = p.cik
               WHERE p.revenue IS NOT NULL AND p.revenue > 0 AND c.sic_code IS NOT NULL"""
        )
    ).all()
    changes = db.execute(
        text(
            """SELECT cik, filing_date FROM filings
               WHERE form_type IN ('8-K', '8-K/A') AND items LIKE '%5.02%'
                 AND filing_date IS NOT NULL"""
        )
    ).all()
    return years, changes


def company_years(years, changes):
    by_cik = defaultdict(dict)
    for cik, fy, end, rev, op, sic2 in years:
        by_cik[cik][fy] = (end, float(rev), float(op) if op is not None else None, sic2)
    filed = defaultdict(list)
    for cik, d in changes:
        filed[cik].append(d)
    rows = []
    for cik, fys in by_cik.items():
        dates = sorted(filed.get(cik, []))
        for fy, (end, rev, op, sic2) in fys.items():
            prev, nxt = fys.get(fy - 1), fys.get(fy + 1)
            if prev is None or nxt is None:
                continue
            start = prev[0]
            n = sum(1 for d in dates if start < d <= end)
            growth = nxt[1] / rev - 1
            if abs(growth) > MAX_ABS_GROWTH:
                continue
            margin_now = op / rev if op is not None else None
            margin_next = nxt[2] / nxt[1] if nxt[2] is not None else None
            dmargin = (
                margin_next - margin_now
                if margin_now is not None
                and margin_next is not None
                and abs(margin_now) < 1
                and abs(margin_next) < 1
                else None
            )
            rows.append({"cik": cik, "fy": fy, "sic2": sic2, "changes": n,
                         "growth": growth, "dmargin": dmargin})  # fmt: skip
    return rows


def with_peers(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["sic2"], r["fy"])].append(r)
    out = []
    for members in groups.values():
        if len(members) < MIN_PEERS:
            continue
        g_med = statistics.median(m["growth"] for m in members)
        margins = [m["dmargin"] for m in members if m["dmargin"] is not None]
        m_med = statistics.median(margins) if len(margins) >= MIN_PEERS else None
        for m in members:
            m["excess_growth"] = m["growth"] - g_med
            m["excess_dmargin"] = (
                m["dmargin"] - m_med if m["dmargin"] is not None and m_med is not None else None
            )
            out.append(m)
    return out


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion, in percent."""
    if not n:
        return (0.0, 0.0)
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(100 * (centre - half), 1), round(100 * (centre + half), 1))


def summarise(rows, label):
    eg = [r["excess_growth"] for r in rows]
    em = [r["excess_dmargin"] for r in rows if r["excess_dmargin"] is not None]
    if not eg:
        return {"group": label, "company_years": 0}
    return {
        "group": label,
        "company_years": len(eg),
        "beat_peer_growth_pct": round(100 * sum(e > 0 for e in eg) / len(eg), 1),
        "beat_peer_growth_ci95": wilson(sum(e > 0 for e in eg), len(eg)),
        "median_excess_growth_pp": round(100 * statistics.median(eg), 2),
        "margin_years": len(em),
        "beat_peer_margin_change_pct": round(100 * sum(e > 0 for e in em) / len(em), 1)
        if em
        else None,
        "median_excess_margin_change_pp": round(100 * statistics.median(em), 2) if em else None,
    }


def report(rows):
    groups = [
        ("No item 5.02 filed in the year", [r for r in rows if r["changes"] == 0]),
        ("At least one item 5.02", [r for r in rows if r["changes"] >= 1]),
        ("Exactly one", [r for r in rows if r["changes"] == 1]),
        ("Two or three", [r for r in rows if 2 <= r["changes"] <= 3]),
        ("Four or more", [r for r in rows if r["changes"] >= 4]),
    ]
    table = [summarise(g, label) for label, g in groups]
    since = defaultdict(list)
    for r in rows:
        since["2004-2014" if r["fy"] <= 2014 else "2015-2025"].append(r)
    by_era = [
        summarise([r for r in since[era] if r["changes"] >= 1], f"With 5.02, fiscal {era}")
        for era in ("2004-2014", "2015-2025")
    ] + [
        summarise([r for r in since[era] if r["changes"] == 0], f"Without, fiscal {era}")
        for era in ("2004-2014", "2015-2025")
    ]
    return table, by_era


def markdown(table, by_era, meta) -> str:
    head = (
        "| Company-years | n | Next-year revenue growth above SIC peers (95% CI) | Median vs peers "
        "(pp) | Operating-margin change above peers | Median vs peers (pp) |\n"
        "|---|---|---|---|---|---|\n"
    )

    def line(t):
        if not t.get("company_years"):
            return f"| {t['group']} | 0 | | | | |"
        return (
            f"| {t['group']} | {t['company_years']:,} | {t['beat_peer_growth_pct']}% "
            f"({t['beat_peer_growth_ci95'][0]}-{t['beat_peer_growth_ci95'][1]}) | "
            f"{t['median_excess_growth_pp']} | {t['beat_peer_margin_change_pct']}% | "
            f"{t['median_excess_margin_change_pp']} |"
        )

    intro = (
        "# Officer and director changes (8-K item 5.02): base rates\n\n"
        "Generated by `scripts/backtest_officer_changes.py`. A company-year has a change when "
        "the company filed at least one 8-K with item 5.02 during that fiscal year. The outcome "
        "is the next fiscal year: revenue growth, and the change in operating margin, each "
        "against the median of companies with the same two-digit SIC code in the same year "
        "(groups of five or more). Figures are annual-report values; next-year moves beyond "
        "+/-500% are left out. The 95% interval is Wilson's.\n\n"
        "This describes what followed; it does not say a change causes anything, and it is "
        "not a signal. Item 5.02 covers departures, appointments, elections and pay changes "
        "alike; the role and kind of change are read only for filings the service has read.\n\n"
    )
    return (
        intro + head + "\n".join(line(t) for t in table) + "\n\nBy period:\n\n" + head
        + "\n".join(line(t) for t in by_era) + "\n\n" + json.dumps(meta, indent=1) + "\n"
    )  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="Write the tables (markdown) here; JSON next to it")
    args = parser.parse_args()
    _, Session = bootstrap()
    db = Session()
    try:
        years, changes = load(db)
        rows = with_peers(company_years(years, changes))
        table, by_era = report(rows)
        meta = {
            "company_years": len(rows),
            "companies": len({r["cik"] for r in rows}),
            "item_502_filings": len(changes),
            "peer_group": f"two-digit SIC and fiscal year, at least {MIN_PEERS} companies",
            "excluded": f"next-year revenue moves beyond +/-{int(MAX_ABS_GROWTH * 100)}%",
        }
        out = markdown(table, by_era, meta)
        print(out)
        if args.out:
            Path(args.out).write_text(out)
            Path(args.out).with_suffix(".json").write_text(
                json.dumps({"table": table, "by_period": by_era, "meta": meta}, indent=1)
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
