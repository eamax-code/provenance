"""What the service covers, for the public /coverage/ page (P-01 pattern): computed when the
quality report runs (and once a day), stored, and only read by requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timeutil import iso_z
from app.db.models import (
    BeneficialOwner,
    Company,
    Filing,
    FinancialFact,
    InsiderFiling,
    ListedInstrument,
    Market,
    Subsidiary,
)
from app.services import ratios
from app.services.fact_normalizer import CONCEPT_MAP, MAPPING_VERSION
from app.services.quality import EDGAR_START, latest_snapshot, suspicious_count
from app.services.stats import read_snapshot, store_snapshot

SNAPSHOT = "snapshot:coverage"
MAX_AGE = timedelta(days=1)
FORMS = (
    ("Annual reports", ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")),
    ("Quarterly reports", ("10-Q", "10-Q/A")),
    ("Current reports with item codes", ("8-K", "8-K/A")),
    ("Registrations and prospectuses", ("S-1", "S-1/A", "F-1", "F-1/A", "424B4", "DRS")),
)


def compute(db: Session, settings: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    filers = int(db.scalar(select(func.count(Company.id))) or 0)
    with_facts = int(db.scalar(select(func.count(distinct(FinancialFact.cik)))) or 0)
    ifrs = int(db.scalar(select(func.count(distinct(FinancialFact.cik))).where(
        FinancialFact.source_taxonomy == "ifrs-full")) or 0)  # fmt: skip
    usable = FinancialFact.quality_status.in_(("ok", "partial"))
    rows = db.execute(
        select(
            FinancialFact.metric,
            func.count(),
            func.sum(case((FinancialFact.quality_status == "ok", 1), else_=0)),
            func.sum(case((FinancialFact.quality_status == "ambiguous_mapping", 1), else_=0)),
            func.count(distinct(case((usable, FinancialFact.cik)))),
            func.min(
                case(
                    (
                        (FinancialFact.quality_status == "ok")
                        & (FinancialFact.period_end >= EDGAR_START),
                        FinancialFact.period_end,
                    )
                )
            ),
        ).group_by(FinancialFact.metric)
    ).all()
    by = {r[0]: r for r in rows}
    metrics = []
    for m, spec in CONCEPT_MAP.items():
        r = by.get(m)
        total = int(r[1]) if r else 0
        metrics.append({
            "metric": m, "label": spec["label"], "statement": spec["statement"],
            "unit_kind": spec["unit"],
            "ok_pct": round(100 * int(r[2] or 0) / total, 1) if total else None,
            "ambiguous_pct": round(100 * int(r[3] or 0) / total, 1) if total else None,
            "companies": int(r[4] or 0) if r else 0,
            "earliest_year": r[5].year if r and r[5] else None,
        })  # fmt: skip
    forms = []
    for label, codes in FORMS:
        n = int(db.scalar(select(func.count()).where(Filing.form_type.in_(codes))) or 0)
        forms.append({"label": label, "forms": list(codes), "filings": n})
    forms.append({"label": "Insider reports (Forms 3, 4, 5)", "forms": ["3", "4", "5"],
                  "filings": int(db.scalar(select(func.count(distinct(
                      InsiderFiling.accession_number)))) or 0)})  # fmt: skip
    holders_cos = int(db.scalar(select(func.count(distinct(BeneficialOwner.subject_cik)))) or 0)
    forms.append({"label": "5% holder reports (Schedules 13D and 13G)",
                  "forms": ["SC 13D", "SC 13G"],
                  "filings": int(db.scalar(select(func.count(distinct(
                      BeneficialOwner.accession_number)))) or 0),
                  "basis": f"read on demand; {holders_cos} companies so far"})  # fmt: skip
    subs_cos = int(db.scalar(select(func.count(distinct(Subsidiary.cik)))) or 0)
    forms.append({"label": "Subsidiary lists (exhibit 21)", "forms": ["EX-21"],
                  "filings": int(db.scalar(select(func.count(distinct(
                      Subsidiary.accession_number)))) or 0),
                  "basis": f"read on demand; {subs_cos} companies so far"})  # fmt: skip
    snap = latest_snapshot(db)
    return {
        "universe": {"filers": filers, "with_facts": with_facts, "ifrs_filers": ifrs},
        "facts_total": int(sum(int(r[1]) for r in rows)),
        "suspicious_periods": suspicious_count(db),
        "metrics": metrics,
        "ratios": [
            {"metric": k, "label": r.label, "formula": r.formula, "unit": ratios.unit_of(r, "USD")}
            for k, r in ratios.RATIOS.items()
        ],  # fmt: skip
        "forms": forms,
        "history": {
            "earliest_filing": _d(db.scalar(select(func.min(Filing.filing_date)))),
            "earliest_fact_year": min(
                (m["earliest_year"] for m in metrics if m["earliest_year"]), default=None
            ),  # fmt: skip
        },
        "freshness": {
            "acceptance_to_here_median_seconds": snap.accept_to_detect_p50_s if snap else None,
            "filings_last_24h": int(
                db.scalar(
                    select(func.count()).where(
                        Filing.filing_date >= (now - timedelta(days=1)).date()
                    )
                )
                or 0
            ),
            "latest_filing_date": _d(db.scalar(select(func.max(Filing.filing_date)))),
        },  # fmt: skip
        "listings": {
            "venues": int(db.scalar(select(func.count(Market.id))) or 0),
            "instruments": int(db.scalar(select(func.count(ListedInstrument.id))) or 0),
        },
        "mapping_version": MAPPING_VERSION,
        "generated_at": iso_z(now),
        "notes": [
            "Counts are of this deployment's data. Figures are as reported to the SEC; missing "
            "values mean no mappable figure was filed, never zero.",
        ],
    }


def _d(value) -> str | None:
    return value.isoformat() if value else None


def refresh(db: Session, settings: Settings) -> dict:
    data = compute(db, settings)
    store_snapshot(db, SNAPSHOT, data)
    return data


def maybe_refresh(db: Session, settings: Settings) -> None:
    """Once a day from the poller: refresh when the stored coverage is a day old or missing."""
    data = read_snapshot(db, SNAPSHOT)
    made = data and data.get("generated_at")
    if (
        not made
        or datetime.fromisoformat(made.replace("Z", "+00:00")) < datetime.now(UTC) - MAX_AGE
    ):
        refresh(db, settings)


def stored(db: Session, settings: Settings) -> dict:
    """The stored coverage, whatever its age; computed once on a cold start."""
    return read_snapshot(db, SNAPSHOT) or refresh(db, settings)
