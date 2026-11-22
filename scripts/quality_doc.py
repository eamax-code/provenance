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
STOPPED = """
with rev as (
  select cik, max(period_end) last_end, max(value) top from financial_facts
  where metric = 'revenue' and period_class = 'annual' and not derived
    and quality_status in ('ok', 'partial') group by cik)
select c.ticker, m.legal_name, r.last_end, round(r.top / 1e9, 1)
from rev r join mart_company m using (cik) left join companies c using (cik)
where r.top >= 1e9 and r.last_end < current_date - 3 * 365
  and m.latest_annual_report_date >= current_date - 730
order by r.top desc"""
LEI = """
with act as (select cik, latest_revenue from mart_company
             where latest_annual_report_date >= current_date - 730)
select count(*) filter (where a.latest_revenue >= 1e9),
       count(l.cik) filter (where a.latest_revenue >= 1e9),
       count(*), count(l.cik)
from act a left join company_lei l using (cik)"""
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
              "% ok counts stored rows; an alternate tag a filing reports beside the preferred "
              "one is stored as ambiguous_mapping by design. Periods with ok counts each company, "
              "unit and period once.", "",
              "| Metric | Facts | % ok | % ambiguous | % suspicious period | Periods with ok | "
              "Companies (ok) | Earliest ok year |",
              "|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for m in per:
        lines.append(f"| {m.metric} | {m.n:,} | {m.ok} | {m.ambiguous} | {m.suspicious} | "
                     f"{period_ok.get(m.metric)}% | {m.companies:,} | {m.earliest} |")  # fmt: skip
    low = [m.metric for m in per if m.ok is not None and float(m.ok) < 93]
    lines += ["", f"Metrics under 93% ok by row: {', '.join(low) if low else 'none'}. Their "
              "periods with an ok figure: " + ", ".join(f"{m} {period_ok.get(m)}%" for m in low)
              + ". The rest are alternate tags in the same filing (for example "
              "AllocatedShareBasedCompensationExpense beside ShareBasedCompensation).",
              ""]  # fmt: skip

    n, c = db.execute(text(CONFLICTS)).one()
    lines += ["## Revenue tag conflicts", "",
              f"Revenue periods where the tags one filing reports disagree: {BEFORE[0]:,} periods "
              f"at {BEFORE[1]:,} companies before the total-first rule, {n:,} at {c:,} now.",
              ""]  # fmt: skip

    stopped = db.execute(text(STOPPED)).all()
    lines += ["## Large filers whose revenue stopped", "",
              f"Active reporters (an annual report in two years) with revenue of $1B or more at "
              f"some point but no annual revenue mapped in the last three years: {len(stopped)}.",
              ""]  # fmt: skip
    for s in stopped[:15]:
        lines.append(f"- {s[0] or '—'} {s[1]}: last {s[2]}, peak ${s[3]}B")
    lines.append("")

    big, big_l, act, act_l = db.execute(text(LEI)).one()
    lines += ["## LEI coverage", "",
              f"- Active $1B+ companies: {big_l:,} of {big:,} ({100 * big_l / max(big, 1):.1f}%)",
              f"- Active reporters: {act_l:,} of {act:,} ({100 * act_l / max(act, 1):.1f}%)",
              "- The rest: SEC records give the home state, not the state of incorporation, for "
              "some filers, and GLEIF does not hold some entities under these names (Chevron).",
              ""]  # fmt: skip

    rev = successions.reviewed()
    stored = sum(r["decision"] == "store" for r in rev.values())
    lines += ["## Successor registrants (K-05)", "",
              f"{len(rev)} pairs found in ten years, all hand-checked against the successor's "
              f"first periodic report: {stored} stored (holding company reorganisations and "
              f"accounting predecessors, each with the sentence quoted), {len(rev) - stored} "
              "rejected (mergers whose accounting acquirer was another company, or no sentence).",
              ""]  # fmt: skip

    lines += ["## Spot check against the 10-K as filed", "", spot_md]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"written": args.out, "spot_ok": ok, "spot_total": total}))
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
