"""Segments (launch plan E-4, first pass): revenue and segment profit by reportable segment, by
geography and by product, as each annual report tags them.

Source: the SEC's Financial Statement and Notes data sets. Companyfacts leaves out dimensional
facts; the data sets keep them, each with its dimensions ("BusinessSegments=IntelligentCloud;",
"Geographical=US;", "ProductOrService=IPhone;"; the axis and member names without "Axis" and
"Member"). Only the registrant's own annual figures (10-K, 20-F, 40-F; a full year; no
co-registrant) are read.

- business: the segment axis, alone or with ConsolidationItems=OperatingSegments.
- geographic: the geographical axis alone. product: the product or service axis alone.
- E-4c: a figure on two of those axes (XOM: Upstream by US and non-US) is summed over the other
  axis, beside any one-axis figures (which win member by member), only when no member of the
  other axis holds others and the segments then add up to the consolidated figure within 1%.
- the all-segments total (US-GAAP ReportableSegmentAggregation..., or a company's own
  "ReportableSegmentsAggregation") is never shown beside real segments.
- reconciling items: ConsolidationItems members such as CorporateNonSegment,
  IntersegmentElimination, SegmentReconcilingItems, MaterialReconcilingItems.
- consolidated: the same tag and period without dimensions.

Metrics: revenue (the first tag whose segments add up, else the first the segments use, among
the revenue tags; finer segments before an all-segments total), operating income, and
pretax income (the segment profit banks report). A member whose value is the sum of others (a
subtotal such as Apple's "Product") is dropped when that makes the segments add up. Status per
kind, metric and year: ok when the segments add up to the consolidated figure within 1%, or the
filing tags a reconciling item; otherwise unreconciled, and still shown with that status.

Labels are made from the member name ("IntelligentCloud" -> "Intelligent Cloud"); the
axis=member string is the stable key.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import CompanySegment
from app.services.sec_client import filing_index_url, normalize_cik

ANNUAL = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
METRIC_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
        "RevenuesNetOfInterestExpense", "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
}  # fmt: skip
TAG_METRIC = {t: m for m, tags in METRIC_TAGS.items() for t in tags}
KIND_AXIS = {"BusinessSegments": "business", "Geographical": "geographic",
             "StatementGeographical": "geographic", "ProductOrService": "product"}  # fmt: skip
OPERATING = "OperatingSegments"
# US-GAAP members that stand for all segments together (Chevron tags its reportable segments'
# total this way): kept where nothing finer adds up, replaced by the segments when they do
TOTAL_MEMBERS = {"ReportableSegmentAggregationBeforeOtherOperatingSegment"}
# and the same total under a company's own member name (Watts: ReportableSegmentsAggregation)
_TOTAL_NAME = re.compile(r"^(Total)?ReportableSegments?(Aggregat\w*|Total|Combined)?$", re.I)


def is_total(key: str) -> bool:
    """A member (or axis=member key) that stands for all reportable segments together."""
    name = key.split(";", 1)[0].split("=", 1)[-1]
    return name in TOTAL_MEMBERS or bool(_TOTAL_NAME.match(name))


TOTAL_LABELS = {"ReportableSegmentAggregationBeforeOtherOperatingSegment":
                "Reportable segments (combined)"}  # fmt: skip
RECONCILING = re.compile(
    r"Corporate|Elimination|Reconcil|Unallocated|NonSegment|Intersegment", re.I
)
TOLERANCE = Decimal("0.01")
BREAKDOWN_TOLERANCE = Decimal("0.001")  # two whole breakdowns in one kind add up exactly
COUNTRIES = {"US": "United States", "CN": "China", "JP": "Japan", "GB": "United Kingdom",
             "DE": "Germany", "FR": "France", "CA": "Canada", "IN": "India", "IE": "Ireland",
             "NL": "Netherlands", "CH": "Switzerland", "KR": "South Korea", "TW": "Taiwan",
             "MX": "Mexico", "BR": "Brazil", "AU": "Australia", "SG": "Singapore"}  # fmt: skip
SINGLE_UNRECONCILED = "single unreconciled member"
LABEL_SOURCE = "member_name"  # E-4b: the filing's own labels from its label linkbase
NOTES = [
    "Segments as each annual report tags them (the segment, geographical and product axes). "
    "Labels are the company's own from the filing (label_source filing_label); members it did "
    "not label keep a label made from the member name (member_name).",
    "Status ok: the segments add up to the consolidated figure within 1%, or the report tags a "
    "reconciling item (corporate, eliminations); unreconciled figures are shown with that status.",
    "A kind with a single member that never adds up is left out (listed under hidden with its "
    "reason); when nothing is left, hidden_reason says why the block is empty.",
]

csv.field_size_limit(50_000_000)


RECONCILING_LABELS = {
    "CorporateNonSegment": "Corporate and other",
    "IntersegmentElimination": "Intersegment eliminations",
    "ConsolidationEliminations": "Intersegment eliminations",
    "SegmentReconcilingItems": "Reconciling items",
    "MaterialReconcilingItems": "Reconciling items",
}


def label(member: str) -> str:
    """'IntelligentCloud' -> 'Intelligent Cloud'; 'AssetandWealthManagementSegment' -> 'Asset and
    Wealth Management'; 'US' -> 'United States'."""
    if member in COUNTRIES:
        return COUNTRIES[member]
    if member in RECONCILING_LABELS:
        return RECONCILING_LABELS[member]
    if member in TOTAL_LABELS:
        return TOTAL_LABELS[member]
    m = re.sub(r"(Segment|Member)$", "", member)
    m = re.sub(r"(?<=[a-z])(and|of|the)(?=[A-Z])", r" \1 ", m)
    m = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z]{2})(?=[A-Z][a-z])", " ", m)
    m = re.sub(r"\bI (?=[A-Z][a-z])", "I", m)  # "IPad", not "I Pad"
    return " ".join(m.split()) or member


def member_label(key: str) -> str:
    """'BusinessSegments=Europe' -> 'Europe'; a segment's own eliminations ->
    'Europe: intersegment eliminations'."""
    parts = dims(key.replace(";", ";") + ";")
    items = parts.pop("ConsolidationItems", None)
    base = label(next(iter(parts.values()))) if parts else ""
    if items and base:
        return f"{base}: {label(items)[:1].lower() + label(items)[1:]}"
    return base or label(items or key)


def dims(segments: str) -> dict[str, str]:
    """'BusinessSegments=Americas;ConsolidationItems=OperatingSegments;' -> {axis: member}."""
    out = {}
    for part in (segments or "").split(";"):
        if "=" in part:
            axis, member = part.split("=", 1)
            out[axis.strip()] = member.strip()
    return out


def classify(d: dict[str, str]) -> tuple[str, str, str] | None:
    """(kind, role, member) for a fact's dimensions, or None when it is not a segment fact."""
    items = d.get("ConsolidationItems")
    rest = {k: v for k, v in d.items() if k != "ConsolidationItems"}
    if not rest and items and RECONCILING.search(items):
        return "business", "reconciling", f"ConsolidationItems={items}"
    if len(rest) != 1:
        return None
    axis, member = next(iter(rest.items()))
    kind = KIND_AXIS.get(axis)
    if kind is None:
        return None
    if items and "Excluding" in items:
        # OperatingSegmentsExcludingIntersegmentElimination (Caterpillar): the segment's figure
        # before eliminations, not a reconciling item; the segment's own figure is read elsewhere
        return None
    if items and items != OPERATING:
        # a segment's own eliminations: keyed apart from the segment itself
        key = f"{axis}={member};ConsolidationItems={items}"
        return (kind, "reconciling", key) if RECONCILING.search(items) else None
    if kind != "geographic" and RECONCILING.search(member):
        return kind, "reconciling", f"{axis}={member}"
    return kind, "segment", f"{axis}={member}"


def classify2(d: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """A fact on two kind axes (XOM: BusinessSegments=Upstream;Geographical=US): for each
    reading, (kind, member key, other axis, other member). Empty when it is not such a fact."""
    items = d.get("ConsolidationItems")
    rest = {k: v for k, v in d.items() if k != "ConsolidationItems"}
    if (items and items != OPERATING) or len(rest) != 2:
        return []
    if any(is_total(v) for v in rest.values()):
        return []
    (a1, m1), (a2, m2) = rest.items()
    k1, k2 = KIND_AXIS.get(a1), KIND_AXIS.get(a2)
    if k1 is None or k2 is None or k1 == k2:
        return []
    out = []
    for (axis, member, kind), (other, other_member) in (
        ((a1, m1, k1), (a2, m2)),
        ((a2, m2, k2), (a1, m1)),
    ):
        if kind != "geographic" and RECONCILING.search(member):
            continue
        out.append((kind, f"{axis}={member}", other, other_member))
    return out


def adds_up(segs: dict[str, Decimal], total: Decimal | None, recon: dict[str, Decimal]) -> bool:
    """The segments alone, or with the tagged reconciling items, make the consolidated figure
    within 1%. Stricter than the status rule (any reconciling item tagged): used where a
    figure is put together rather than read."""
    if total is None or len(segs) < 2:
        return False
    s = sum(segs.values(), Decimal(0))
    return _close(s, total) or _close(s + sum(recon.values(), Decimal(0)), total)


def summed_over(
    by_other: dict[str, dict[str, dict[str, Decimal]]],
    total: Decimal | None,
    recon: dict[str, Decimal],
    base: dict[str, Decimal] | None = None,
) -> dict[str, Decimal] | None:
    """Segments from two-axis facts, summed over the other axis, beside any one-axis segments
    (`base`, which win member by member: Chevron's All Other is tagged alone, Upstream and
    Downstream by US and non-US). Only when (1) no member of the other axis is a subtotal of
    others for any segment (NonUS holding Canada would count twice) and (2) the segments then
    add up to the consolidated figure. Otherwise None."""
    base = base or {}
    for other in sorted(by_other):
        cells = {m: v for m, v in by_other[other].items() if m not in base}
        if not cells or any(subtotals(vals) for vals in cells.values()):
            continue
        summed = {**base, **{m: sum(vals.values(), Decimal(0)) for m, vals in cells.items()}}
        if adds_up(summed, total, recon):
            return summed
    return None


def drop_reconciling_subtotals(recon: dict[str, Decimal]) -> dict[str, Decimal]:
    """Reconciling items whose value is the sum of two or more others of the same sign (a total
    of per-segment eliminations; eliminations plus corporate items) are dropped."""
    if len(recon) < 3:
        return recon
    parents: set[str] = set()
    for sign in (1, -1):
        same = {k: v * sign for k, v in recon.items() if v * sign > 0}
        parents |= subtotals(same)
    return {k: v for k, v in recon.items() if k not in parents}


def _whole(part: list[str], members: dict[str, Decimal], signed: bool) -> bool:
    """A set of members that can be one whole breakdown: no two members with the same value (one
    region tagged twice, Northern Technologies' "Inside the USA" and "US"), and for revenue no
    negative member (an elimination, not a region: Frequency Electronics' US -4.2M)."""
    values = [members[k] for k in part if members[k]]
    if len(values) != len(set(values)):
        return False
    return signed or all(members[k] >= 0 for k in part)


def one_breakdown(
    members: dict[str, Decimal], total: Decimal | None, signed: bool = False
) -> dict[str, Decimal]:
    """Members of one kind that hold two whole breakdowns (Caterpillar's geography: four regions,
    and US with non-US, each making the total) are split, and the finer one kept. Only when the
    members split into two sets that each make the total within 0.1%: two whole breakdowns add
    up exactly, while a near miss is a mix of totals and their parts (Spok, Vertex); otherwise
    as they are."""
    if total is None or not total or len(members) < 4 or len(members) > 16:
        return members
    if _close(sum(members.values(), Decimal(0)), total):
        return members
    keys = sorted(members)
    best = None
    for n in range(2, len(keys) - 1):
        for combo in combinations(keys, n):
            part = set(combo)
            rest = [k for k in keys if k not in part]
            if len(rest) < 2:
                continue
            exact = abs(total) * BREAKDOWN_TOLERANCE
            if (
                abs(sum(members[k] for k in part) - total) <= exact
                and abs(sum(members[k] for k in rest) - total) <= exact
                and _whole(list(part), members, signed)
                and _whole(rest, members, signed)
            ):
                finer = max((sorted(part), sorted(rest)), key=lambda x: (len(x), x))
                if best is None or len(finer) > len(best):
                    best = finer
        if best:
            break
    return {k: members[k] for k in best} if best else members


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= abs(b) * TOLERANCE


def subtotals(members: dict[str, Decimal]) -> set[str]:
    """Members whose value is the sum of two or more other members (within 0.5%): a parent such
    as Apple's "Product" (iPhone + Mac + iPad + Wearables)."""
    out = set()
    keys = [k for k, v in members.items() if v > 0]
    for k in keys:
        others = [o for o in keys if o != k and members[o] < members[k]]
        for n in range(2, min(len(others), 6) + 1):
            if any(abs(sum(members[o] for o in combo) - members[k]) <= members[k] * Decimal("0.005")
                   for combo in combinations(others, n)):  # fmt: skip
                out.add(k)
                break
    return out


def drop_subtotals(
    members: dict[str, Decimal], total: Decimal | None, reconciling: Decimal = Decimal(0)
) -> dict[str, Decimal]:
    """Drop subtotal members when the segments then add up (with any reconciling items) to the
    total and do not with them."""
    if total is None or not members or _close(sum(members.values()) + reconciling, total):
        return members
    parents = subtotals(members)
    rest = {k: v for k, v in members.items() if k not in parents}
    if parents and rest and _close(sum(rest.values()) + reconciling, total):
        return rest
    return members


def _ymd(v: str) -> date | None:
    try:
        return datetime.strptime(v[:8], "%Y%m%d").date()
    except ValueError:
        return None


def parse_notes_zip(path: str | Path) -> list[dict]:
    """Segment rows (and their reconciling and consolidated figures) from one data set."""
    source = "sec:fsn:" + Path(path).stem
    with zipfile.ZipFile(path) as z:

        def rows(name):
            fh = z.open(next(n for n in z.namelist() if n.lower().endswith(name)))
            return csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace",
                                                   newline=""),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)  # fmt: skip

        subs = {r["adsh"]: r for r in rows("sub.tsv") if (r.get("form") or "").upper() in ANNUAL}
        dimmap = {r["dimhash"]: r["segments"] for r in rows("dim.tsv")}
        # (adsh, kind, metric, tag, ddate, unit) -> {"segment": {member: v}, "reconciling": {...}}
        groups: dict[tuple, dict] = {}
        # the same key -> {other axis: {member: {other member: value}}} for two-axis facts
        pairs: dict[tuple, dict] = {}
        operating: dict[tuple, dict[str, Decimal]] = {}
        consolidated: dict[tuple, Decimal] = {}
        fh = z.open(next(n for n in z.namelist() if n.lower().endswith("num.tsv")))
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
        col = {n: i for i, n in enumerate(text.readline().rstrip("\n").split("\t"))}
        for line in text:
            if line[:20] not in subs:
                continue
            f = line.rstrip("\n").split("\t")
            tag = f[col["tag"]]
            if tag not in TAG_METRIC or f[col["qtrs"]] != "4" or f[col["iprx"]] != "0":
                continue
            if f[col["coreg"]] or not f[col["value"]]:
                continue
            adsh, ddate, unit = f[col["adsh"]], f[col["ddate"]], f[col["uom"]]
            value = Decimal(f[col["value"]])
            if f[col["dimn"]] == "0":
                consolidated[(adsh, tag, ddate, unit)] = value
                continue
            d = dims(dimmap.get(f[col["dimh"]], ""))
            c = classify(d)
            if c is None:
                for kind, member, other, other_member in classify2(d):
                    k = (adsh, kind, TAG_METRIC[tag], tag, ddate, unit)
                    cell = pairs.setdefault(k, {}).setdefault(other, {}).setdefault(member, {})
                    cell[other_member] = value
                continue
            kind, role, member = c
            k = (adsh, kind, TAG_METRIC[tag], tag, ddate, unit)
            g = groups.setdefault(k, {"segment": {}, "reconciling": {}})
            if role == "segment" and d.get("ConsolidationItems") == OPERATING:
                # the member's operating-segments part, beside its own total when both are
                # tagged (XOM: Sales and other operating revenue); resolved below
                operating.setdefault(k, {})[member] = value
                continue
            g[role][member] = value
    # reconciling rows that are the sum of others (Caterpillar tags eliminations per segment,
    # their total, and eliminations with corporate items) would count twice
    for g in groups.values():
        g["reconciling"] = drop_reconciling_subtotals(g["reconciling"])
    # where a filing tags both, the member's own total wins unless only the operating-segments
    # parts add up (XOM's product lines add up with the totals; some filers' only with the parts)
    for k, parts in operating.items():
        g = groups[k]
        adsh, kind, _, tag, ddate, unit = k
        total = consolidated.get((adsh, tag, ddate, unit))
        recon = g["reconciling"] if kind == "business" else {}
        own, other = {**parts, **g["segment"]}, {**g["segment"], **parts}
        # members with an operating figure and no own total; an all-segments total or a zero
        # does not make two bases (California Resources, Watts)
        extra = {m for m in set(parts) - set(g["segment"]) if parts[m] and not is_total(m)}
        if extra and set(parts) & set(g["segment"]):
            # own totals for only some members would mix two bases (Caterpillar: Power & Energy
            # external, the others gross of intersegment sales): the parts, unless only the
            # own totals add up
            only_own = adds_up(own, total, recon) and not adds_up(other, total, recon)
            g["segment"] = own if only_own else other
            continue
        g["segment"] = (
            other if adds_up(other, total, recon) and not adds_up(own, total, recon) else own
        )
    # E-4c: a group with no one-axis segments takes them from two-axis facts summed over the
    # other axis, when that is safe and adds up (one-axis figures always win)
    for k, by_other in pairs.items():
        g = groups.get(k)
        adsh, kind, _, tag, ddate, unit = k
        total = consolidated.get((adsh, tag, ddate, unit))
        recon = g["reconciling"] if g and kind == "business" else {}
        base = g["segment"] if g else {}
        core = {m: v for m, v in base.items() if not is_total(m)}
        if base and core == base and adds_up(base, total, recon):
            continue  # the one-axis segments already add up: nothing to put together
        summed = summed_over(by_other, total, recon, core)
        if summed:
            groups.setdefault(k, {"segment": {}, "reconciling": {}})["segment"] = summed
    # the all-segments total beside real segments would count them twice (Caterpillar): it
    # stays only where it is all there is besides "all other"
    for g in groups.values():
        segs = g["segment"]
        totals = [m for m in segs if is_total(m)]
        finer = [m for m in segs if m not in totals and "AllOther" not in m]
        for m in totals if finer else ():
            del segs[m]
    # per filing, kind and metric: the first tag whose segments add up in the latest period,
    # else the first tag the filing reports segments with (XOM's product revenue: one line under
    # the contract-revenue tag, three that add up under Revenues)
    latest: dict[tuple, str] = {}
    for adsh, kind, metric, tag, ddate, _ in groups:
        k = (adsh, kind, metric, tag)
        latest[k] = max(latest.get(k, ddate), ddate)
    fits: set[tuple] = set()
    for (adsh, kind, metric, tag, ddate, unit), g in groups.items():
        if ddate != latest[(adsh, kind, metric, tag)]:
            continue
        recon = g["reconciling"] if kind == "business" else {}
        if adds_up(g["segment"], consolidated.get((adsh, tag, ddate, unit)), recon):
            fits.add((adsh, kind, metric, tag))

    coarse = {(a, k, m, t) for (a, k, m, t, _, _), g in groups.items()
              if any(is_total(x) for x in g["segment"])}  # fmt: skip

    def rank(adsh, kind, metric, tag):
        # adds up first, then segments finer than the all-segments total (Chevron's Revenues
        # tag has Upstream and Downstream; its contract-revenue tag only the total)
        k = (adsh, kind, metric, tag)
        return k not in fits, k in coarse, METRIC_TAGS[metric].index(tag)

    chosen: dict[tuple, str] = {}
    for adsh, kind, metric, tag, _, _ in groups:
        k = (adsh, kind, metric)
        if k not in chosen or rank(*k, tag) < rank(*k, chosen[k]):
            chosen[k] = tag
    # D-04: one unit per filing, kind and metric: the unit with the most periods; on a tie not
    # USD (a USD figure beside another currency is a convenience translation)
    periods_by_unit: dict[tuple, dict[str, set]] = {}
    for adsh, kind, metric, tag, ddate, unit in groups:
        if chosen[(adsh, kind, metric)] == tag:
            periods_by_unit.setdefault((adsh, kind, metric), {}).setdefault(unit, set()).add(ddate)
    unit_of = {k: max(v, key=lambda u: (len(v[u]), u != "USD"))
               for k, v in periods_by_unit.items()}  # fmt: skip
    out = []
    for (adsh, kind, metric, tag, ddate, unit), g in groups.items():
        if chosen[(adsh, kind, metric)] != tag or not g["segment"]:
            continue
        if unit_of.get((adsh, kind, metric)) != unit:
            continue
        sub, end = subs[adsh], _ymd(ddate)
        if end is None:
            continue
        total = consolidated.get((adsh, tag, ddate, unit))
        recon = g["reconciling"] if kind == "business" else {}
        segs = drop_subtotals(g["segment"], total, sum(recon.values(), Decimal(0)))
        if kind != "business":
            segs = one_breakdown(segs, total, signed=metric != "revenue")
        ok = total is not None and (_close(sum(segs.values()), total) or bool(recon))
        status = "ok" if ok else "unreconciled"
        base = {"accession_number": adsh, "kind": kind, "metric": metric, "period_end": end,
                "cik": normalize_cik(sub["cik"]), "form_type": sub["form"].upper(),
                "fiscal_year": int(sub["fy"]) if (sub.get("fy") or "").isdigit() else None,
                "filed_date": _ymd(sub["filed"]), "tag": tag, "unit": unit, "status": status,
                "source": source}  # fmt: skip
        for role, items in (("segment", segs), ("reconciling", recon)):
            for member, v in items.items():
                out.append({**base, "member": member, "label": member_label(member),
                            "role": role, "value": v})  # fmt: skip
        if total is not None:
            out.append({**base, "member": "consolidated", "label": "Consolidated",
                        "role": "consolidated", "value": total})  # fmt: skip
    return [r for r in out if r["filed_date"] is not None]


def load(db: Session, path: str | Path) -> dict:
    rows = parse_notes_zip(path)
    accs = sorted({r["accession_number"] for r in rows})
    for i in range(0, len(accs), 1000):
        db.execute(delete(CompanySegment).where(
            CompanySegment.accession_number.in_(accs[i : i + 1000])))  # fmt: skip
    for i in range(0, len(rows), 5000):
        db.execute(insert(CompanySegment), rows[i : i + 5000])
    db.commit()
    unrec = len({(r["accession_number"], r["kind"], r["metric"]) for r in rows
                 if r["status"] != "ok"})  # fmt: skip
    groups = len({(r["accession_number"], r["kind"], r["metric"]) for r in rows})
    return {"rows": len(rows), "reports": len(accs), "groups": groups, "unreconciled": unrec}


def _drop_cancelling(metrics: dict, segs: dict, recon: dict) -> None:
    """Reconciling rows that net to zero beside segments that add up on their own, in every shown
    year, are left out for that metric (Chevron: +$145M and -$145M of eliminations)."""
    for metric, m in metrics.items():
        cons = m["consolidated"]
        if not cons:
            continue
        cancel = True
        for p, total in cons.items():
            seg = sum(s["values"].get(metric, {}).get(p) or 0 for s in segs.values())
            rec = sum(r["values"].get(metric, {}).get(p) or 0 for r in recon.values())
            tol = abs(total) * float(TOLERANCE)
            if abs(seg - total) > tol or abs(rec) > tol / 2:
                cancel = False
                break
        if cancel:
            for r in recon.values():
                r["values"].pop(metric, None)
    for key in [k for k, r in recon.items() if not r["values"]]:
        del recon[key]


def for_company(db: Session, cik: str, as_of: date | None = None, years: int = 3) -> dict | None:
    """The overview block: the latest annual report with segments, each kind with its segments'
    figures for up to three fiscal years as that report gives them."""
    stmt = select(CompanySegment).where(CompanySegment.cik == cik)
    if as_of:
        stmt = stmt.where(CompanySegment.filed_date <= as_of)
    order = (CompanySegment.filed_date.desc(), CompanySegment.accession_number.desc())
    latest = db.scalars(stmt.order_by(*order).limit(1)).first()
    if latest is None:
        return None
    rows = list(db.scalars(select(CompanySegment).where(
        CompanySegment.accession_number == latest.accession_number)))  # fmt: skip
    kinds, hidden = [], []
    for kind in ("business", "geographic", "product"):
        krows = [r for r in rows if r.kind == kind]
        if not krows:
            continue
        periods = sorted({r.period_end for r in krows}, reverse=True)[:years]
        keep = [r for r in krows if r.period_end in periods]
        metrics: dict[str, dict] = {}
        segs: dict[str, dict] = {}
        recon: dict[str, dict] = {}
        for r in keep:
            p = r.period_end.isoformat()
            m = metrics.setdefault(r.metric, {"tag": r.tag, "unit": r.unit, "status": {},
                                              "consolidated": {}})  # fmt: skip
            m["status"][p] = r.status
            if r.role == "consolidated":
                m["consolidated"][p] = float(r.value)
                continue
            target = segs if r.role == "segment" else recon
            source = r.label_source or LABEL_SOURCE
            new = {"key": r.member, "label": r.label, "label_source": source, "values": {}}
            item = target.setdefault(r.member, new)
            item["values"].setdefault(r.metric, {})[p] = float(r.value)
        latest_p = periods[0].isoformat()
        rev = metrics.get("revenue", {}).get("consolidated", {}).get(latest_p)
        ordered = sorted(segs.values(), key=lambda s: -(s["values"].get("revenue", {})
                                                         .get(latest_p) or 0))  # fmt: skip
        # a share of revenue only where the segments add up (ok); never from unreconciled figures
        rev_ok = metrics.get("revenue", {}).get("status", {}).get(latest_p) == "ok"
        # and only where the segments alone make the total: segment figures that include sales
        # between segments (XOM's, eliminated below them) would give shares adding to over 100%
        seg_sum = sum(s["values"].get("revenue", {}).get(latest_p) or 0 for s in ordered)
        rev_ok = rev_ok and bool(rev) and abs(seg_sum - rev) <= abs(rev) * float(TOLERANCE)
        for s in ordered:
            v = s["values"].get("revenue", {}).get(latest_p)
            share = round(v / rev * 100, 1) if rev_ok and v is not None and rev else None
            s["share_of_revenue_pct"] = share
        if len(ordered) == 1 and not any(
            st == "ok" for m in metrics.values() for st in m["status"].values()
        ):
            # one member that never adds up tells the reader nothing and can mislead (XOM's
            # "Sales and other operating revenue" standing in for its four segments)
            hidden.append({"kind": kind, "reason": SINGLE_UNRECONCILED,
                           "member": ordered[0]["label"]})  # fmt: skip
            continue
        _drop_cancelling(metrics, segs, recon)
        kinds.append({"kind": kind, "periods": [p.isoformat() for p in periods],
                      "metrics": metrics, "segments": ordered,
                      "reconciling": list(recon.values())})  # fmt: skip
    return {
        "filing": {
            "form_type": latest.form_type, "accession_number": latest.accession_number,
            "fiscal_year": latest.fiscal_year, "filed_date": latest.filed_date.isoformat(),
            "source_url": filing_index_url(cik, latest.accession_number),
        },
        "kinds": kinds,
        "hidden": hidden,
        # set when every kind was hidden: the block has nothing to show, and says why
        "hidden_reason": SINGLE_UNRECONCILED if hidden and not kinds else None,
        "notes": NOTES,
    }  # fmt: skip
