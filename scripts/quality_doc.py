#!/usr/bin/env python
"""Write the data-quality report for a mapping pass (docs/data-quality-<date>.md).

  python scripts/quality_doc.py --out docs/data-quality-2026-11-22.md --fsn .sec_bulk/fsn

Per metric quality, the revenue tag conflicts, large filers whose revenue stopped, LEI coverage,
successor registrants, and a spot check of eight companies against the 10-K as filed: each
figure is compared with the value the SEC's Financial Statement and Notes data sets carry for
the same filing, tag and period (an extraction independent of the companyfacts feed), or, for a
10-K not yet in those data sets, with the earnings release that stated it (E-2 rules).
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import text

from app.services import first_reported, releases, successions
from app.services.fact_normalizer import MAPPING_VERSION
from app.services.prospectus import to_text
from app.services.sec_client import SecClient, filing_index_url

SPOT = [("AAPL", "0000320193"), ("JPM", "0000019617"), ("XOM (old CIK)", "0000034088"),
        ("XOM (new CIK)", "0002115436"), ("DUK", "0001326160"), ("O", "0000726728"),
        ("BRK", "0001067983"), ("LIN", "0001707925")]  # fmt: skip
SPOT_METRICS = ("revenue", "net_income", "total_assets", "eps_diluted")
BEFORE = (57_872, 2_075)  # revenue periods with disagreeing tags under 1.3.0 rules (measured)

PER_METRIC = """
select metric, count(*) n,
  round(100.0 * avg((quality_status = 'ok')::int), 1) ok,
  round(100.0 * avg((quality_status = 'ambiguous_mapping')::int), 1) ambiguous,
  round(100.0 * avg((period_end < date '1993-01-01' or period_end > filed_date + 730)::int), 2)
    suspicious,
  count(distinct cik) filter (where quality_status = 'ok') companies,
  extract(year from min(period_end) filter (where quality_status = 'ok'
    and period_end >= date '1993-01-01'))::int earliest
from financial_facts where not derived group by metric order by metric"""
PERIOD_OK = """
with g as (
  select metric, cik, unit, period_start, period_end,
         bool_or(quality_status in ('ok', 'partial')) has_ok
  from financial_facts where not derived group by 1, 2, 3, 4, 5)
select metric, round(100.0 * avg(has_ok::int), 1) from g group by 1"""
CONFLICTS = """
select count(*), count(distinct cik) from (
  select cik, unit, period_start, period_end from financial_facts
  where metric = 'revenue' and not derived group by 1, 2, 3, 4
  having bool_and(quality_status not in ('ok', 'partial'))
     and bool_or(quality_status = 'ambiguous_mapping')) t"""
# $1B+ cohorts by USD equivalent at the Federal Reserve H.10 average rate for each fiscal year
# (app.services.fx); companies reporting in a currency H.10 does not cover are listed apart
STOPPED = """
select cik from financial_facts f join mart_company m using (cik)
where f.metric = 'revenue' and f.period_class = 'annual' and not f.derived
  and f.quality_status in ('ok', 'partial') and m.latest_annual_report_date >= current_date - 730
group by cik having max(f.period_end) < current_date - 3 * 365"""
ANNUAL_REVENUE = """
select f.value, f.unit, f.period_start, f.period_end from financial_facts f
where f.cik = :cik and f.metric = 'revenue' and f.period_class = 'annual' and not f.derived
  and f.quality_status in ('ok', 'partial')"""
LEI = """
select m.cik, m.latest_revenue, m.reporting_currency, m.latest_revenue_period_end, m.legal_name,
       l.cik is not null linked
from mart_company m left join company_lei l using (cik)
where m.latest_annual_report_date >= current_date - 730"""
SEGMENT_CAUSES = """
with g as (
  select accession_number, kind, metric, period_end,
         sum(value) filter (where role = 'segment') seg,
         max(value) filter (where role = 'consolidated') tot,
         count(*) filter (where role = 'segment') n
  from company_segments where status = 'unreconciled' group by 1, 2, 3, 4),
c as (select case
   when tot is null then 'no consolidated figure under the same tag'
   when n = 1 then 'a single segment tagged'
   when tot <> 0 and seg > tot * 2.2 then 'segments far above the total (several breakdowns mixed)'
   when tot <> 0 and seg > tot * 1.01
     then 'segments above the total (overlapping breakdowns, subtotals)'
   when seg >= 0 and seg < tot * 0.99 then 'segments below the total (partial disclosure)'
   else 'other (signs, zero or negative totals)' end cause from g)
select cause, count(*) from c group by 1 order by 2 desc"""
LATEST = """
select f.metric, f.value, f.unit, f.source_tag, f.period_start, f.period_end, f.accession_number,
       f.filed_date, f.form_type, f.quality_status
from financial_facts f
where f.cik = :cik and f.metric = any(:metrics) and not f.derived
  and f.period_class = 'annual' and f.quality_status in ('ok', 'partial')
  and f.form_type in ('10-K', '10-K/A', '20-F', '40-F')
  and f.period_end = (select max(g.period_end) from financial_facts g where g.cik = f.cik
      and g.metric = 'revenue' and g.period_class = 'annual' and not g.derived
      and g.form_type in ('10-K', '10-K/A', '20-F', '40-F'))
order by f.metric, f.filed_date desc"""


def fsn_values(folder: Path, accessions: set[str]) -> dict[tuple, Decimal]:
    """(adsh, tag, ddate, qtrs, uom) -> value, the registrant's own facts, for these filings."""
    out: dict[tuple, Decimal] = {}
    for z in sorted(folder.glob("*_notes.zip")):
        with zipfile.ZipFile(z) as zf, zf.open("num.tsv") as fh:
            rd = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            col = {n: i for i, n in enumerate(rd.readline().rstrip("\n").split("\t"))}
            for line in rd:
                if line[:20] not in accessions:
                    continue
                f = line.rstrip("\n").split("\t")
                if f[col["dimn"]] != "0" or f[col["coreg"]] or not f[col["value"]]:
                    continue
                if f[col["iprx"]] != "0":
                    continue  # a repeat of the same fact at a coarser rounding
                key = (f[col["adsh"]], f[col["tag"]], f[col["ddate"]], f[col["qtrs"]],
                       f[col["uom"]])  # fmt: skip
                out[key] = Decimal(f[col["value"]])
    return out


def _around(line: str, metric: str, value) -> str:
    """The words around the stated number, without table pipes."""
    import re

    line = line.replace("|", "/")
    for pattern, _ in first_reported.renderings(value, metric):
        m = re.search(pattern, line)
        if m:
            return "…" + line[max(0, m.start() - 45) : m.end() + 10].strip() + "…"
    return line[:60]


def fmt(v: Decimal | float | None, unit: str) -> str:
    if v is None:
        return "—"
    v = float(v)
    if "shares" in unit and "/" in unit:
        return f"{v:.2f}"
    return f"{v / 1e6:,.0f}M"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--fsn", default=".sec_bulk/fsn")
    ap.add_argument("--spot-only", action="store_true", help="Print the spot-check table only")
    args = ap.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    today = date.today()
    lines = [f"# Data quality, mapping {MAPPING_VERSION} ({today.isoformat()})", ""]

    # spot check
    facts = {}
    for label, cik in SPOT:
        rows = db.execute(text(LATEST), {"cik": cik, "metrics": list(SPOT_METRICS)}).all()
        seen = {}
        for r in rows:
            seen.setdefault(r.metric, r)  # latest filed per metric
        facts[label] = (cik, seen)
    accessions = {r.accession_number for _, seen in facts.values() for r in seen.values()}
    fsn = fsn_values(Path(args.fsn), accessions)
    spot = [
        "| Company | FY end | Metric | Provenance | 10-K as filed | Check | Filing |",
        "|---|---|---|---|---|---|---|",
    ]
    ok = total = 0
    for label, (cik, seen) in facts.items():
        if not seen:
            spot.append(f"| {label} | — | — | no annual report in the data | | | |")
            continue
        release_text = None
        for m in SPOT_METRICS:
            r = seen.get(m)
            if r is None:
                note = " (Berkshire reports basic EPS per Class A share)" if label == "BRK" else ""
                spot.append(f"| {label} | | {m} | not reported{note} | | | |")
                continue
            qtrs = "0" if r.period_start is None else "4"
            unit = r.unit
            uom = unit.split("/")[0] if unit.endswith("/shares") else unit  # the data sets: "USD"
            key = (r.accession_number, r.source_tag, r.period_end.strftime("%Y%m%d"), qtrs, uom)
            filed = fsn.get(key)
            if filed is not None:
                same = abs(float(filed) - float(r.value)) < 0.5 * (0.01 if "/" in unit else 1)
                check, shown = ("same" if same else "DIFFERENT"), fmt(filed, unit)
            else:
                if release_text is None:  # 10-K not in the data sets yet: its earnings release
                    rel = db.execute(text(
                        "select accession_number from filings where cik = :c and form_type like "
                        "'8-K%' and items like '%2.02%' and filing_date > :e and filing_date <= :f "
                        "order by filing_date limit 1"), {"c": cik, "e": r.period_end,
                                                         "f": r.filed_date}).scalar()  # fmt: skip
                    release_text = ""
                    if rel:
                        f = db.execute(text("select * from filings where accession_number = :a"),
                                       {"a": rel}).mappings().first()  # fmt: skip
                        url = releases.exhibit_url(sec.get_text(f["source_url"]).data)
                        release_text = to_text(sec.get_text(url).data) if url else ""
                hit = first_reported.stated(release_text, m, r.value) if release_text else None
                same = hit is not None
                check = "same (earnings release)" if same else "not checked"
                shown = _around(hit[1], m, r.value) if hit else "—"
            total += 1
            ok += same
            link = filing_index_url(cik, r.accession_number)
            spot.append(f"| {label} | {r.period_end} | {m} | {fmt(r.value, unit)} | {shown} | "
                        f"{check} | [{r.form_type}]({link}) |")  # fmt: skip
    spot_md = "\n".join(spot) + f"\n\n{ok} of {total} figures match the filing as filed.\n"
    if args.spot_only:
        print(spot_md)
        return 0

    per = db.execute(text(PER_METRIC)).all()
    period_ok = dict(db.execute(text(PERIOD_OK)).all())
    lines += ["## Per metric", "",
              "Periods with an ok figure: for each company and period, is there an ok figure "
              "(what a user meets). Rows ok counts stored rows: when a filing reports a figure "
              "under two tags, the alternate one is kept and marked ambiguous, never deleted, "
              "which is why the row % is lower for sbc, d_and_a and revenue.", "",
              "| Metric | Periods with an ok figure | Rows ok (alternate tags kept for audit) | "
              "% ambiguous | % suspicious period | Facts | Companies (ok) | Earliest ok year |",
              "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for m in per:
        lines.append(f"| {m.metric} | {period_ok.get(m.metric)}% | {m.ok}% | {m.ambiguous} | "
                     f"{m.suspicious} | {m.n:,} | {m.companies:,} | {m.earliest} |")  # fmt: skip
    low = [m.metric for m in per if m.ok is not None and float(m.ok) < 93]
    lines += ["", f"Metrics under 93% ok by row: {', '.join(low) if low else 'none'}. Their "
              "periods with an ok figure: " + ", ".join(f"{m} {period_ok.get(m)}%" for m in low)
              + ". The rest are alternate tags in the same filing (for example "
              "AllocatedShareBasedCompensationExpense beside ShareBasedCompensation).",
              ""]  # fmt: skip

    from app.services import mapping_check

    old_sql = "select count(*), count(distinct cik) from financial_facts where mapping_version<>:v"
    old_rows = db.execute(text(old_sql), {"v": MAPPING_VERSION}).one()
    lines += [f"Facts on an older mapping: {old_rows[0]:,} rows at {old_rows[1]:,} companies; "
              f"check_mapping: {mapping_check.check(db)['summary']}. The reviewed exceptions "
              "(app/data/mapping_exceptions.csv) are observations the SEC's company facts no "
              "longer publish, so no pass can re-read them; they are kept as reported, on the "
              "mapping that read them.", ""]  # fmt: skip

    n, c = db.execute(text(CONFLICTS)).one()
    lines += ["## Revenue tag conflicts", "",
              f"Revenue periods where the tags one filing reports disagree: {BEFORE[0]:,} periods "
              f"at {BEFORE[1]:,} companies before the total-first rule, {n:,} at {c:,} now.",
              ""]  # fmt: skip

    from app.services import fx

    big_stopped, uncovered_stopped = [], []
    for (cik,) in db.execute(text(STOPPED)).all():
        best, last_end, cur = None, None, None
        for value, unit, ps, pe in db.execute(text(ANNUAL_REVENUE), {"cik": cik}).all():
            last_end = max(last_end or pe, pe)
            cur = unit[:3] if unit else None
            usd = fx.usd_equivalent(db, value, cur, ps, pe)
            if usd is not None and (best is None or usd > best):
                best = usd
        ticker, name = db.execute(text("select c.ticker, m.legal_name from mart_company m "
                                       "left join companies c using (cik) where m.cik = :c"),
                                  {"c": cik}).one()  # fmt: skip
        if best is not None and best >= 10**9:
            big_stopped.append((ticker, name, last_end, round(float(best) / 1e9, 1), cur))
        elif best is None and cur and cur != "USD":
            uncovered_stopped.append((ticker, name, last_end, cur))
    big_stopped.sort(key=lambda r: -r[3])
    lines += ["## Large filers whose revenue stopped", "",
              "Revenue of $1B or more at some point, by USD equivalent at the Federal Reserve "
              "H.10 average rate for each fiscal year (companies' own figures stay in the "
              "currency they report in), an annual report in the last two years, but no annual "
              "revenue mapped in the last three years.", "",
              f"- $1B+ by USD equivalent: {len(big_stopped)}.",
              f"- In a currency H.10 does not cover (no USD equivalent): "
              f"{len(uncovered_stopped)}.", ""]  # fmt: skip
    for r in big_stopped[:20]:
        lines.append(f"- {r[0] or '—'} {r[1]} ({r[4]}): last {r[2]}, peak ${r[3]}B equivalent")
    for r in uncovered_stopped[:15]:
        lines.append(f"- {r[0] or '—'} {r[1]} ({r[3]}, not covered by H.10): last {r[2]}")
    lines += ["", "Known causes (mapping 1.4.1 notes): banks reporting in IFRS (21, such as HSBC, "
              "Santander, BBVA, UBS, SMFG) tag their total operating income only in "
              "company-specific extension tags, which companyfacts leaves out, and ifrs-full has "
              "no standard total; adding net interest and net fee income would leave out trading "
              "and other income, so their revenue stays absent rather than built. Williams' "
              "total and contract revenue disagree in the same 10-K (eliminations); the "
              "income-statement line would decide it, measured for a later mapping.",
              ""]  # fmt: skip

    from datetime import timedelta

    big = big_l = act = act_l = 0
    uncovered: dict[str, list[str]] = {}
    for _cik, rev_, cur, pe, name, linked in db.execute(text(LEI)).all():
        act += 1
        act_l += bool(linked)
        if rev_ is None or pe is None:
            continue
        usd = fx.usd_equivalent(db, rev_, cur, pe - timedelta(days=364), pe)
        if usd is None and cur and cur != "USD":
            uncovered.setdefault(cur, []).append(name)
        elif usd is not None and usd >= 10**9:
            big += 1
            big_l += bool(linked)
    lines += ["## LEI coverage", "",
              f"- Active reporters with $1B+ revenue by USD equivalent (Federal Reserve H.10 "
              f"average rate for the fiscal year): {big_l:,} of {big:,} "
              f"({100 * big_l / max(big, 1):.1f}%)",
              f"- All active reporters: {act_l:,} of {act:,} ({100 * act_l / max(act, 1):.1f}%)",
              f"- Reporting in a currency H.10 does not cover, so outside the $1B+ cohort: "
              f"{sum(len(v) for v in uncovered.values())} "
              f"({', '.join(f'{k} {len(v)}' for k, v in sorted(uncovered.items()))})",
              "- The rest: GLEIF does not hold some entities under these names (Chevron).",
              ""]  # fmt: skip
    for cur, names in sorted(uncovered.items()):
        lines.append(f"  - {cur}: {', '.join(sorted(names)[:12])}"
                     + (f" and {len(names) - 12} more" if len(names) > 12 else ""))  # fmt: skip
    lines.append("")

    rev = successions.reviewed()
    stored = sum(r["decision"] == "store" for r in rev.values())
    lines += ["## Successor registrants (K-05)", "",
              f"{len(rev)} pairs found in ten years, all hand-checked against the successor's "
              f"first periodic report: {stored} stored (holding company reorganisations and "
              f"accounting predecessors, each with the sentence quoted), {len(rev) - stored} "
              "rejected (mergers whose accounting acquirer was another company, or no sentence).",
              ""]  # fmt: skip

    causes = db.execute(text(SEGMENT_CAUSES)).all()
    total = sum(n for _, n in causes) or 1
    lines += ["## Unreconciled segments (E-4)", "",
              "Segment figures are shown with status unreconciled when they do not add up to the "
              "consolidated figure within 1% and no reconciling item is tagged. Causes, per "
              "filing, kind, metric and year:", ""]  # fmt: skip
    lines += [f"- {cause}: {n:,} ({100 * n / total:.0f}%)" for cause, n in causes]
    lines += ["", "### Two-axis segments and single-member blocks (E-4c, 2026-11-22)", "",
              "Segments tagged on two axes (XOM: each segment by US and non-US) are now summed "
              "over the other axis when no member of that axis holds others and the segments "
              "then add up to the consolidated figure within 1%; one-axis figures win member by "
              "member. The revenue tag whose segments add up (and are finer than an "
              "all-segments total) is preferred, and the all-segments total is never shown "
              "beside real segments. A kind with one member that never adds up is hidden, with "
              "its reason in the API.", "",
              "Dry run against every company's latest report before the reload: 417 of 4,174 "
              "blocks changed: 206 kinds added, 108 moved from unreconciled to ok, 140 changed "
              "values or members within an ok block; none removed and none from ok to "
              "unreconciled. Hand-check: a first sample of 30 found 2 wrong (an all-segments "
              "total counted twice, an intersegment line shown as a product); after tightening, "
              "a fresh seeded random sample of 30 found 1 (a company-named total, then fixed).",
              "",
              "The 358 companies whose latest block had at most one member per kind: 21 now "
              "show segments that add up; 210 are single-segment companies (the one segment is "
              "the consolidated figure); 75 had a single unreconciled member, now hidden; 52 "
              "report segment profit only, no revenue by segment. XOM: Energy Products $291.6B, "
              "Upstream $107.2B, Chemical Products $33.0B, Specialty Products $20.5B; with "
              "corporate and eliminations, $332.2B, the consolidated figure exactly.",
              ""]  # fmt: skip

    results = Path(__file__).resolve().parents[1] / "docs" / "mapping-1.5.0-results.json"
    if results.exists():
        r = json.loads(results.read_text())
        t, b = r["tiebreak"], r["bank"]
        lines += ["## Mapping 1.5.0: what changed (two rules, shown apart)", "",
                  "Counted against the stored values just before the pass (each figure is a "
                  "revenue value for one filing and period).", "",
                  "| Rule | Values changed | Newly ok | Lost ok | Companies |",
                  "|---|---|---|---|---|",
                  f"| Income-statement line settles disagreeing tags | {t['value_changed']:,} | "
                  f"{t['new_ok']:,} | {t['lost_ok']:,} | {t['companies']:,} "
                  f"({t['companies_changed']:,} with a changed value) |",
                  f"| IFRS bank total income | {b['value_changed']:,} | {b['new_ok']:,} | "
                  f"{b['lost_ok']:,} | {b['companies']:,} |", "",
                  f"Tag-only changes (the same value now cited under the income-statement tag): "
                  f"{r.get('tag_only', 0):,}.", "",
                  "Bank revenue = the total income line on the income statement, after interest "
                  "expense, as the bank labels it; only where the filing's own income statement "
                  "shows ifrs-full RevenueAndOperatingIncome or GrossProfit under such a label, "
                  "and only for banks and credit institutions (SIC 6000-6199). It is net of "
                  "interest expense, so not comparable with US banks' gross revenue.", "",
                  f"Hand-checks: {r.get('hand_check', '')}", ""]  # fmt: skip

    rates = first_reported.match_rates(db)
    matched = sum(m for m, _ in rates.values())
    eligible = sum(e for _, e in rates.values()) or 1
    lines += ["## First reported in earnings releases (E-2)", "",
              f"Figures an 8-K item 2.02 release stated with the same value, of those it could "
              f"have stated (the period's own 10-Q or 10-K, a stored release in its window): "
              f"{matched:,} of {eligible:,} ({100 * matched / eligible:.1f}%). Balance-sheet and "
              "cash-flow figures are often not printed in releases.", "",
              "| Metric | Matched | Eligible | Rate |", "|---|---|---|---|"]  # fmt: skip
    lines += [
        f"| {k} | {m:,} | {e:,} | {100 * m / max(e, 1):.0f}% |" for k, (m, e) in rates.items()
    ]
    lines.append("")

    lines += ["## Spot check against the 10-K as filed", "", spot_md]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"written": args.out, "spot_ok": ok, "spot_total": total}))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
