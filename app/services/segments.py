"""Segments (launch plan E-4, first pass): revenue and segment profit by reportable segment, by
geography and by product, as each annual report tags them.

Source: the SEC's Financial Statement and Notes data sets. Companyfacts leaves out dimensional
facts; the data sets keep them, each with its dimensions ("BusinessSegments=IntelligentCloud;",
"Geographical=US;", "ProductOrService=IPhone;"; the axis and member names without "Axis" and
"Member"). Only the registrant's own annual figures (10-K, 20-F, 40-F; a full year; no
co-registrant) are read.

- business: the segment axis, alone or with ConsolidationItems=OperatingSegments.
- geographic: the geographical axis alone. product: the product or service axis alone.
- reconciling items: ConsolidationItems members such as CorporateNonSegment,
  IntersegmentElimination, SegmentReconcilingItems, MaterialReconcilingItems.
- consolidated: the same tag and period without dimensions.

Metrics: revenue (the first tag the segments use among the revenue tags), operating income, and
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
RECONCILING = re.compile(r"Corporate|Elimination|Reconcil|Unallocated|NonSegment", re.I)
TOLERANCE = Decimal("0.01")
COUNTRIES = {"US": "United States", "CN": "China", "JP": "Japan", "GB": "United Kingdom",
             "DE": "Germany", "FR": "France", "CA": "Canada", "IN": "India", "IE": "Ireland",
             "NL": "Netherlands", "CH": "Switzerland", "KR": "South Korea", "TW": "Taiwan",
             "MX": "Mexico", "BR": "Brazil", "AU": "Australia", "SG": "Singapore"}  # fmt: skip
LABEL_SOURCE = "member_name"  # E-4b: the filing's own labels from its label linkbase
NOTES = [
    "Segments as each annual report tags them (the segment, geographical and product axes); "
    "labels are made from the tagged member names.",
    "Status ok: the segments add up to the consolidated figure within 1%, or the report tags a "
    "reconciling item (corporate, eliminations); unreconciled figures are shown with that status.",
]

csv.field_size_limit(50_000_000)


RECONCILING_LABELS = {
    "CorporateNonSegment": "Corporate and other (not a segment)",
    "IntersegmentElimination": "Intersegment eliminations",
    "SegmentReconcilingItems": "Reconciling items",
    "MaterialReconcilingItems": "Material reconciling items",
}


def label(member: str) -> str:
    """'IntelligentCloud' -> 'Intelligent Cloud'; 'AssetandWealthManagementSegment' -> 'Asset and
    Wealth Management'; 'US' -> 'United States'."""
    if member in COUNTRIES:
        return COUNTRIES[member]
    if member in RECONCILING_LABELS:
        return RECONCILING_LABELS[member]
    m = re.sub(r"(Segment|Member)$", "", member)
    m = re.sub(r"(?<=[a-z])(and|of|the)(?=[A-Z])", r" \1 ", m)
    m = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z]{2})(?=[A-Z][a-z])", " ", m)
    m = re.sub(r"\bI (?=[A-Z][a-z])", "I", m)  # "IPad", not "I Pad"
    return " ".join(m.split()) or member


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
    if items and items != OPERATING:
        return (kind, "reconciling", f"{axis}={member}") if RECONCILING.search(items) else None
    if kind != "geographic" and RECONCILING.search(member):
        return kind, "reconciling", f"{axis}={member}"
    return kind, "segment", f"{axis}={member}"


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
            c = classify(dims(dimmap.get(f[col["dimh"]], "")))
            if c is None:
                continue
            kind, role, member = c
            g = groups.setdefault((adsh, kind, TAG_METRIC[tag], tag, ddate, unit),
                                  {"segment": {}, "reconciling": {}})  # fmt: skip
            g[role][member] = value
    # per filing, kind and metric: the first tag whose segments the filing reports
    chosen: dict[tuple, str] = {}
    for adsh, kind, metric, tag, _, _ in groups:
        k = (adsh, kind, metric)
        tags = METRIC_TAGS[metric]
        if k not in chosen or tags.index(tag) < tags.index(chosen[k]):
            chosen[k] = tag
    out = []
    for (adsh, kind, metric, tag, ddate, unit), g in groups.items():
        if chosen[(adsh, kind, metric)] != tag or not g["segment"]:
            continue
        sub, end = subs[adsh], _ymd(ddate)
        if end is None:
            continue
        total = consolidated.get((adsh, tag, ddate, unit))
        recon = g["reconciling"] if kind == "business" else {}
        segs = drop_subtotals(g["segment"], total, sum(recon.values(), Decimal(0)))
        ok = total is not None and (_close(sum(segs.values()), total) or bool(recon))
        status = "ok" if ok else "unreconciled"
        base = {"accession_number": adsh, "kind": kind, "metric": metric, "period_end": end,
                "cik": normalize_cik(sub["cik"]), "form_type": sub["form"].upper(),
                "fiscal_year": int(sub["fy"]) if (sub.get("fy") or "").isdigit() else None,
                "filed_date": _ymd(sub["filed"]), "tag": tag, "unit": unit, "status": status,
                "source": source}  # fmt: skip
        for role, items in (("segment", segs), ("reconciling", recon)):
            for member, v in items.items():
                out.append({**base, "member": member, "label": label(member.split("=", 1)[1]),
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
    kinds = []
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
            new = {"key": r.member, "label": r.label, "label_source": LABEL_SOURCE, "values": {}}
            item = target.setdefault(r.member, new)
            item["values"].setdefault(r.metric, {})[p] = float(r.value)
        latest_p = periods[0].isoformat()
        rev = metrics.get("revenue", {}).get("consolidated", {}).get(latest_p)
        ordered = sorted(segs.values(), key=lambda s: -(s["values"].get("revenue", {})
                                                         .get(latest_p) or 0))  # fmt: skip
        for s in ordered:
            v = s["values"].get("revenue", {}).get(latest_p)
            s["share_of_revenue_pct"] = round(v / rev * 100, 1) if v is not None and rev else None
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
        "notes": NOTES,
    }  # fmt: skip
