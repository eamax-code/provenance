"""Normalize SEC company-facts XBRL JSON into canonical metrics.

Mapping is versioned (MAPPING_VERSION). Rules (see AGENTS.md §6):
- Absent facts stay absent; values are never defaulted to 0; sign is preserved.
- Every candidate tag's observations are kept. The highest-precedence tag with data for a
  given (unit, period) is "preferred" and gets `ok`; alternates get `ambiguous_mapping`.
  If candidate tags disagree on value for the same period, the preferred one is also
  `ambiguous_mapping`.
- Period class is derived from the actual duration, not from the SEC `fp` label, so a
  year-to-date 6/9-month fact is never presented as a quarter.
- Quarter derivation by subtraction is explicit, opt-in at query time, and marked
  derived=true with the source observations recorded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

MAPPING_VERSION = "1.0.0"

# Ordered by precedence (first wins when several tags cover the same period).
CONCEPT_MAP: dict[str, dict[str, Any]] = {
    "revenue": {
        "period_type": "duration",
        "candidates": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
    },
    "operating_income": {"period_type": "duration", "candidates": ["OperatingIncomeLoss"]},
    "net_income": {
        "period_type": "duration",
        # NetIncomeLoss is the only candidate on purpose: attributable-to-parent and
        # available-to-common variants are different concepts and are not substituted.
        "candidates": ["NetIncomeLoss"],
    },
    "total_assets": {"period_type": "instant", "candidates": ["Assets"]},
    "operating_cash_flow": {
        "period_type": "duration",
        "candidates": ["NetCashProvidedByUsedInOperatingActivities"],
    },
}

SUPPORTED_METRICS = tuple(CONCEPT_MAP.keys())
TAXONOMIES = ("us-gaap",)

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A", "10-QT", "10-QT/A"}

ANNUAL_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)


@dataclass
class NormalizedFact:
    metric: str
    value: Decimal | None
    unit: str
    currency: str | None
    period_start: date | None
    period_end: date
    period_type: str
    period_class: str
    fiscal_year: int | None
    fiscal_period: str | None
    form_type: str | None
    filed_date: date | None
    accession_number: str | None
    source_tag: str
    source_taxonomy: str
    source_url: str
    mapping_version: str
    quality_status: str
    derived: bool = False
    derivation: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def observation_key(self) -> str:
        parts = [
            self.metric,
            self.source_taxonomy,
            self.source_tag,
            self.unit,
            self.period_start.isoformat() if self.period_start else "",
            self.period_end.isoformat(),
            self.accession_number or "",
            "derived" if self.derived else "reported",
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def source_payload_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "tag": self.source_tag,
                    "unit": self.unit,
                    "start": self.period_start.isoformat() if self.period_start else None,
                    "end": self.period_end.isoformat(),
                    "val": str(self.value) if self.value is not None else None,
                    "accn": self.accession_number,
                    "fy": self.fiscal_year,
                    "fp": self.fiscal_period,
                    "form": self.form_type,
                    "filed": self.filed_date.isoformat() if self.filed_date else None,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_value(value: Any) -> tuple[Decimal | None, bool]:
    """Return (decimal_or_none, ok). ok=False means the source value was unparseable."""
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, False
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, False
    if not d.is_finite():
        return None, False
    return d, True


def currency_from_unit(unit: str) -> str | None:
    """Map an XBRL unit to an ISO currency code only when the unit is a plain currency."""
    if unit and len(unit) == 3 and unit.isalpha() and unit.isupper():
        return unit
    return None


def classify_duration(start: date, end: date) -> str:
    days = (end - start).days + 1
    if ANNUAL_DAYS[0] <= days <= ANNUAL_DAYS[1]:
        return "annual"
    if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
        return "quarterly"
    if 160 <= days <= 290:
        return "ytd"
    return "other"


def classify_instant(form: str | None, fp: str | None) -> str:
    if form in ANNUAL_FORMS and (fp or "").upper() == "FY":
        return "annual"
    if form in QUARTERLY_FORMS:
        return "quarterly"
    if form in ANNUAL_FORMS:
        return "annual"
    return "other"


def _filing_url(cik: str, accession: str | None, base: str) -> str:
    from app.services.sec_client import company_facts_url, filing_index_url

    if accession:
        return filing_index_url(cik, accession, base)
    return company_facts_url(cik)


def normalize_company_facts(
    payload: dict,
    cik: str,
    www_base: str = "https://www.sec.gov",
) -> list[NormalizedFact]:
    """Normalize the SEC companyfacts payload for one company into canonical facts."""
    facts_root = payload.get("facts") if isinstance(payload, dict) else None
    if not isinstance(facts_root, dict):
        return []

    results: list[NormalizedFact] = []
    for metric, spec in CONCEPT_MAP.items():
        expected_ptype = spec["period_type"]
        candidate_facts: list[tuple[int, NormalizedFact]] = []
        for taxonomy in TAXONOMIES:
            tax = facts_root.get(taxonomy)
            if not isinstance(tax, dict):
                continue
            for precedence, tag in enumerate(spec["candidates"]):
                concept = tax.get(tag)
                if not isinstance(concept, dict):
                    continue
                units = concept.get("units")
                if not isinstance(units, dict):
                    continue
                for unit, observations in units.items():
                    if not isinstance(observations, list):
                        continue
                    for obs in observations:
                        nf = _normalize_observation(
                            metric, expected_ptype, taxonomy, tag, unit, obs, cik, www_base
                        )
                        if nf is not None:
                            candidate_facts.append((precedence, nf))
        _apply_precedence(candidate_facts)
        results.extend(nf for _, nf in candidate_facts)
    return results


def _normalize_observation(
    metric: str,
    expected_ptype: str,
    taxonomy: str,
    tag: str,
    unit: str,
    obs: Any,
    cik: str,
    www_base: str,
) -> NormalizedFact | None:
    if not isinstance(obs, dict):
        return None
    end = parse_date(obs.get("end"))
    if end is None:
        return None  # a fact without a period end cannot be placed in time; skipped
    start = parse_date(obs.get("start"))
    notes: list[str] = []
    value, ok = parse_value(obs.get("val"))
    accession = obs.get("accn") if isinstance(obs.get("accn"), str) else None
    form = obs.get("form") if isinstance(obs.get("form"), str) else None
    filed = parse_date(obs.get("filed"))
    fy = (
        obs.get("fy")
        if isinstance(obs.get("fy"), int) and not isinstance(obs.get("fy"), bool)
        else None
    )
    fp = obs.get("fp") if isinstance(obs.get("fp"), str) else None

    if start is not None:
        period_type = "duration"
        period_class = classify_duration(start, end)
    else:
        period_type = "instant"
        period_class = classify_instant(form, fp)

    if period_type != expected_ptype:
        notes.append(f"source period type {period_type} differs from expected {expected_ptype}")

    if not ok:
        quality = "invalid_source_value"
    elif period_type != expected_ptype:
        quality = "ambiguous_mapping"
    elif not (accession and form and filed and fy is not None and fp):
        quality = "partial"
        notes.append("one or more of accession, form, filed date, fiscal year/period missing")
    else:
        quality = "ok"

    return NormalizedFact(
        metric=metric,
        value=value,
        unit=str(unit),
        currency=currency_from_unit(str(unit)),
        period_start=start,
        period_end=end,
        period_type=period_type,
        period_class=period_class,
        fiscal_year=fy,
        fiscal_period=fp,
        form_type=form,
        filed_date=filed,
        accession_number=accession,
        source_tag=tag,
        source_taxonomy=taxonomy,
        source_url=_filing_url(cik, accession, www_base),
        mapping_version=MAPPING_VERSION,
        quality_status=quality,
        notes=notes,
    )


def _apply_precedence(candidates: list[tuple[int, NormalizedFact]]) -> None:
    """Mark non-preferred and conflicting candidate tags as ambiguous_mapping (in place)."""
    by_period: dict[tuple, list[tuple[int, NormalizedFact]]] = {}
    for prec, nf in candidates:
        key = (nf.unit, nf.period_start, nf.period_end)
        by_period.setdefault(key, []).append((prec, nf))
    for group in by_period.values():
        tags_present = {nf.source_tag for _, nf in group}
        if len(tags_present) <= 1:
            continue
        best_prec = min(prec for prec, _ in group)
        # latest filed value per tag for conflict detection
        latest_by_tag: dict[str, NormalizedFact] = {}
        for _, nf in group:
            cur = latest_by_tag.get(nf.source_tag)
            if cur is None or (nf.filed_date or date.min) > (cur.filed_date or date.min):
                latest_by_tag[nf.source_tag] = nf
        values = {nf.value for nf in latest_by_tag.values() if nf.value is not None}
        conflict = len(values) > 1
        for prec, nf in group:
            if nf.quality_status == "invalid_source_value":
                continue
            if prec != best_prec:
                nf.quality_status = "ambiguous_mapping"
                nf.notes.append(
                    "alternate candidate tag; a higher-precedence tag covers this period"
                )
            elif conflict:
                nf.quality_status = "ambiguous_mapping"
                nf.notes.append("candidate tags disagree on value for this period")


def derive_quarters(facts: list[NormalizedFact]) -> list[NormalizedFact]:
    """Derive standalone quarter facts by subtraction: (YTD/FY to e2) - (YTD to e1).

    Only within the same metric, tag, unit and period_start, only when both inputs are
    reported (not derived), `ok`, and the difference spans 80-100 days. The result is
    marked derived=true, quality_status=derived, and carries both source observations.
    """
    derived: list[NormalizedFact] = []
    groups: dict[tuple, list[NormalizedFact]] = {}
    for f in facts:
        if (
            f.period_type != "duration"
            or f.derived
            or f.period_start is None
            or f.quality_status != "ok"
            or f.value is None
        ):
            continue
        groups.setdefault((f.metric, f.source_tag, f.unit, f.period_start), []).append(f)

    for (metric, tag, unit, _start), items in groups.items():
        # latest filed observation per period_end
        latest: dict[date, NormalizedFact] = {}
        for f in items:
            cur = latest.get(f.period_end)
            if cur is None or (f.filed_date or date.min) > (cur.filed_date or date.min):
                latest[f.period_end] = f
        ends = sorted(latest)
        for i in range(1, len(ends)):
            longer = latest[ends[i]]
            shorter = latest[ends[i - 1]]
            q_start = shorter.period_end + timedelta(days=1)
            q_days = (longer.period_end - q_start).days + 1
            if not (QUARTER_DAYS[0] <= q_days <= QUARTER_DAYS[1]):
                continue
            if longer.period_class not in ("annual", "ytd") or shorter.period_class not in (
                "quarterly",
                "ytd",
            ):
                continue
            value = longer.value - shorter.value  # type: ignore[operator]
            derived.append(
                NormalizedFact(
                    metric=metric,
                    value=value,
                    unit=unit,
                    currency=longer.currency,
                    period_start=q_start,
                    period_end=longer.period_end,
                    period_type="duration",
                    period_class="quarterly",
                    fiscal_year=longer.fiscal_year,
                    fiscal_period=longer.fiscal_period,
                    form_type=longer.form_type,
                    filed_date=longer.filed_date,
                    accession_number=longer.accession_number,
                    source_tag=tag,
                    source_taxonomy=longer.source_taxonomy,
                    source_url=longer.source_url,
                    mapping_version=MAPPING_VERSION,
                    quality_status="derived",
                    derived=True,
                    derivation={
                        "method": "subtraction",
                        "formula": "value(longer_period) - value(shorter_period)",
                        "minuend": _obs_ref(longer),
                        "subtrahend": _obs_ref(shorter),
                    },
                    notes=["derived by subtraction of two reported year-to-date observations"],
                )
            )
    return derived


def _obs_ref(f: NormalizedFact) -> dict:
    return {
        "source_tag": f.source_tag,
        "unit": f.unit,
        "period_start": f.period_start.isoformat() if f.period_start else None,
        "period_end": f.period_end.isoformat(),
        "value": str(f.value) if f.value is not None else None,
        "accession_number": f.accession_number,
        "filed_date": f.filed_date.isoformat() if f.filed_date else None,
        "form_type": f.form_type,
    }
